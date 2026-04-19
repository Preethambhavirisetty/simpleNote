"""Three-tier intent detection: regex → exemplar similarity → LLM fallback.

Layer 0 (Regex):    Catches obvious patterns (corpus_stats, conversation_meta,
                    keyword_count, temporal, list_notes) with zero latency.
Layer 1 (Exemplar): Embeds the query, searches the intent exemplar collection
                    in Qdrant.  Picks the single best match per intent (10
                    results), sorts by score, evaluates the top 2.
Layer 2 (LLM):      Falls back to structured LLM classification with the top
                    exemplars injected as few-shot context.

Exemplar decision logic:
    top-1 score ≥ 0.92           → return directly (high confidence)
    top-1 & top-2 same intent,
        both ≥ 0.78             → return intent  (agreement confirms)
    otherwise                    → fall through to LLM
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field

import structlog

from core.config import (
    INTENT_LLM_MAX_TOKENS,
    QDRANT_COLLECTION,
    QDRANT_URL,
)
from core.feature_flags import is_enabled
from pipeline.llm import llm_call

log = structlog.get_logger()

# ── All recognized intents ───────────────────────────────────────────────

VALID_INTENTS = frozenset({
    "semantic",
    "locate_note",
    "list_notes",
    "keyword_count",
    "temporal",
    "presence_check",
    "compare_notes",
    "corpus_stats",
    "conversation_meta",
    "clarify_intent",
})

# Maps each intent to the execution strategy consumed by pipeline/strategies.py.
# Intents without a dedicated handler fall through to "semantic".
INTENT_ACTIONS: dict[str, str] = {
    "semantic":          "semantic",
    "locate_note":       "semantic",
    "list_notes":        "listing",
    "keyword_count":     "keyword_count",
    "temporal":          "temporal",
    "presence_check":    "semantic",
    "compare_notes":     "semantic",
    "corpus_stats":      "corpus_stats",
    "conversation_meta": "conversation_meta",
    "clarify_intent":    "clarify_intent",
}

# ── Exemplar similarity thresholds ───────────────────────────────────────

EXEMPLAR_HIGH_THRESHOLD = 0.92
EXEMPLAR_AGREE_THRESHOLD = 0.78

# ── QueryPlan ────────────────────────────────────────────────────────────


@dataclass
class QueryPlan:
    """Result of intent classification.

    ``strategy`` maps to a handler in ``pipeline/strategies.py``.
    ``intent`` carries the fine-grained intent label.
    """
    strategy: str
    intent: str = "semantic"
    search_term: str | None = None
    confidence: float = 1.0
    source: str = "regex"
    slots: dict = field(default_factory=dict)


# ── IntentStore (Qdrant-backed exemplar bank) ────────────────────────────

INTENT_COLLECTION = f"{QDRANT_COLLECTION}_intents"


class IntentStore:
    """Thin Qdrant wrapper for ingesting and querying intent exemplars.

    Reuses the same embedding model (``Settings.embed_model``) as the main
    RAG pipeline so exemplar vectors live in the same latent space.
    """

    def __init__(self):
        from qdrant_client import QdrantClient, models as _models
        from llama_index.core import Settings as _Settings

        self._client = QdrantClient(url=QDRANT_URL)
        self._models = _models
        self._settings = _Settings
        self._ensure_collection()

    def _ensure_collection(self):
        if self._client.collection_exists(INTENT_COLLECTION):
            return
        sample = self._settings.embed_model.get_text_embedding("dimension check")
        self._client.create_collection(
            collection_name=INTENT_COLLECTION,
            vectors_config=self._models.VectorParams(
                size=len(sample),
                distance=self._models.Distance.COSINE,
            ),
        )
        self._client.create_payload_index(
            collection_name=INTENT_COLLECTION,
            field_name="intent",
            field_schema=self._models.PayloadSchemaType.KEYWORD,
        )
        log.info("intent_store.created", collection=INTENT_COLLECTION)

    # ── ingestion ─────────────────────────────────────────────────────

    def ingest(
        self,
        exemplars: dict[str, list[str]],
        source: str = "seed",
    ) -> int:
        """Embed and upsert exemplars. ``exemplars`` maps intent → list[text]."""
        points = []
        for intent, texts in exemplars.items():
            if intent not in VALID_INTENTS:
                log.warning("intent_store.unknown_intent", intent=intent)
                continue
            for i, text in enumerate(texts):
                vec = self._settings.embed_model.get_text_embedding(text)
                point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{intent}:{text}"))
                points.append(
                    self._models.PointStruct(
                        id=point_id,
                        vector=vec,
                        payload={
                            "text": text,
                            "intent": intent,
                            "source": source,
                            "created_at": int(time.time()),
                        },
                    )
                )
        if points:
            self._client.upsert(
                collection_name=INTENT_COLLECTION, points=points,
            )
        log.info("intent_store.ingested", count=len(points), source=source)
        return len(points)

    # ── search ────────────────────────────────────────────────────────

    def search_best_per_intent(
        self, query: str, *, fetch_limit: int = 50,
    ) -> list[tuple[str, str, float]]:
        """Return the single best-scoring exemplar per intent, sorted by score.

        Executes one broad search, groups by intent, keeps the highest
        scorer per intent, and returns them in descending score order.
        Result length equals the number of intents that have exemplars.

        Returns list of ``(exemplar_text, intent, cosine_score)``.
        """
        vec = self._settings.embed_model.get_query_embedding(query)
        try:
            results = self._client.query_points(
                collection_name=INTENT_COLLECTION,
                query=vec,
                limit=fetch_limit,
            ).points
        except Exception:
            log.warning("intent_store.search_failed", exc_info=True)
            return []

        best: dict[str, tuple[str, float]] = {}
        for p in results:
            intent = p.payload["intent"]
            if intent not in best or p.score > best[intent][1]:
                best[intent] = (p.payload["text"], p.score)

        ranked = [
            (text, intent, score)
            for intent, (text, score) in best.items()
        ]
        ranked.sort(key=lambda x: x[2], reverse=True)
        return ranked

    def count(self) -> int:
        return self._client.count(
            collection_name=INTENT_COLLECTION, exact=True,
        ).count

    def close(self):
        self._client.close()


# Module-level lazy singleton
_intent_store: IntentStore | None = None


def get_intent_store() -> IntentStore | None:
    """Return a shared IntentStore, creating it on first call.

    Returns None if the store cannot be initialised (e.g. Qdrant is down).
    """
    global _intent_store
    if _intent_store is None:
        try:
            _intent_store = IntentStore()
        except Exception:
            log.warning("intent_store.init_failed", exc_info=True)
            return None
    return _intent_store


# ── Regex tier ───────────────────────────────────────────────────────────

_REGEX_RULES: list[tuple[re.Pattern, str, int | None]] = [
    # corpus_stats
    (re.compile(
        r"how\s+many\s+(?:notes?|folders?)\s+(?:do\s+)?I\s+have", re.I,
    ), "corpus_stats", None),
    (re.compile(
        r"(?:total|count)\s+(?:of\s+)?(?:all\s+)?(?:notes?|folders?)", re.I,
    ), "corpus_stats", None),
    (re.compile(
        r"(?:largest|biggest|smallest|longest|shortest)\s+note", re.I,
    ), "corpus_stats", None),
    (re.compile(r"(?:empty|unused)\s+folders?", re.I), "corpus_stats", None),

    # conversation_meta
    (re.compile(
        r"(?:repeat|say)\s+(?:that|last|your\s+(?:last|previous))", re.I,
    ), "conversation_meta", None),
    (re.compile(
        r"what\s+(?:did|were)\s+(?:i|we)\s+(?:just\s+)?(?:ask|talk)", re.I,
    ), "conversation_meta", None),

    # keyword_count
    (re.compile(
        r"how\s+many\s+times.*?"
        r"(?:say|said|mention(?:ed)?|wrote|write|use[ds]?|written|type[ds]?)"
        r"\s+['\"]?(.+?)['\"]?\s*\??$",
        re.I,
    ), "keyword_count", 1),
    (re.compile(
        r"(?:count|total\s+number\s+of)\s+.*?['\"](.+?)['\"]", re.I,
    ), "keyword_count", 1),

    # temporal
    (re.compile(
        r"when\s+did\s+(?:i|we)\s+.*?"
        r"(?:say|said|mention|write|wrote|add|added|note|create)",
        re.I,
    ), "temporal", None),

    # list_notes
    (re.compile(
        r"(?:list\s+all|show\s+(?:me\s+)?all|what\s+are\s+all)\b", re.I,
    ), "list_notes", None),
]

# ── LLM classification prompt ───────────────────────────────────────────

_LLM_SYSTEM_PROMPT = """\
You are an intent classifier for a personal notes app.

## User's Query:
"{user_query}"

## Most Similar Known Examples (from our database):
{exemplar_block}

## Available Intents:
- semantic: Understand/recall/summarize note content
- locate_note: Find a specific note by content or keyword
- list_notes: List/enumerate notes matching criteria
- keyword_count: Count occurrences or quantify
- temporal: Time-based note queries
- presence_check: Yes/no check if something exists
- compare_notes: Compare across multiple notes
- corpus_stats: Statistics about the note collection
- conversation_meta: Questions about this conversation
- clarify_intent: Query is too ambiguous

## Task:
Based on the user's query and the similar examples above, classify the intent.
If the similar examples disagree, use your judgment based on the query's actual meaning.

Respond ONLY with valid JSON:
{{"intent": "<intent_name>", "confidence": 0.0-1.0, "slots": {{"topic": null, "time_range": null, "scope": null}}, "reasoning": "<one sentence>"}}"""


# ── QueryPlanner ─────────────────────────────────────────────────────────


class QueryPlanner:
    """Three-tier intent classifier: regex → exemplar similarity → LLM."""

    def plan(self, query: str) -> QueryPlan:
        # Layer 0: regex fast-path
        plan = self._try_regex(query)
        if plan is not None:
            return plan

        # Fetch exemplar results once (shared between layer 1 and 2)
        exemplar_results: list[tuple[str, str, float]] = []
        if is_enabled("chat.intent_exemplar"):
            store = get_intent_store()
            if store is not None:
                exemplar_results = store.search_best_per_intent(query)

        # Layer 1: exemplar similarity check
        plan = self._evaluate_exemplars(exemplar_results)
        if plan is not None:
            return plan

        # Layer 2: LLM fallback
        if is_enabled("chat.intent_llm"):
            return self._try_llm(query, exemplar_results)

        return QueryPlan(
            strategy="semantic", intent="semantic",
            confidence=1.0, source="default",
        )

    # ── Layer 0 ───────────────────────────────────────────────────────

    @staticmethod
    def _try_regex(query: str) -> QueryPlan | None:
        for pattern, intent, group_idx in _REGEX_RULES:
            m = pattern.search(query)
            if m:
                search_term = (
                    m.group(group_idx).strip() if group_idx is not None else None
                )
                return QueryPlan(
                    strategy=INTENT_ACTIONS.get(intent, "semantic"),
                    intent=intent,
                    search_term=search_term,
                    confidence=1.0,
                    source="regex",
                )
        return None

    # ── Layer 1 ───────────────────────────────────────────────────────

    @staticmethod
    def _evaluate_exemplars(
        results: list[tuple[str, str, float]],
    ) -> QueryPlan | None:
        """Evaluate per-intent best scores.

        Each entry in *results* represents a different intent's best exemplar.
        - Top-1 ≥ 0.92 → return directly (single exemplar is very close).
        - Top-1 and top-2 both ≥ 0.78 → the exemplar space covers the
          query well; trust the top-scoring intent.
        """
        if not results:
            return None

        _text_1, intent_1, score_1 = results[0]

        if score_1 >= EXEMPLAR_HIGH_THRESHOLD:
            log.info(
                "intent.exemplar_high",
                intent=intent_1, score=round(score_1, 3),
            )
            return QueryPlan(
                strategy=INTENT_ACTIONS.get(intent_1, "semantic"),
                intent=intent_1,
                confidence=round(score_1, 3),
                source="exemplar",
            )

        if len(results) >= 2:
            _text_2, _intent_2, score_2 = results[1]
            if (
                score_1 >= EXEMPLAR_AGREE_THRESHOLD
                and score_2 >= EXEMPLAR_AGREE_THRESHOLD
            ):
                log.info(
                    "intent.exemplar_confident",
                    intent=intent_1,
                    scores=(round(score_1, 3), round(score_2, 3)),
                )
                return QueryPlan(
                    strategy=INTENT_ACTIONS.get(intent_1, "semantic"),
                    intent=intent_1,
                    confidence=round(score_1, 3),
                    source="exemplar",
                )

        log.debug(
            "intent.exemplar_low",
            top_3=[(i, round(s, 3)) for _, i, s in results[:3]],
        )
        return None

    # ── Layer 2 ───────────────────────────────────────────────────────

    @staticmethod
    def _try_llm(
        query: str,
        exemplar_results: list[tuple[str, str, float]],
    ) -> QueryPlan:
        # Results are already best-per-intent sorted by score; take top 3
        top_3 = exemplar_results[:3]
        if top_3:
            lines = [
                f'{i}. "{text}" \u2192 intent: {intent} (similarity: {score:.2f})'
                for i, (text, intent, score) in enumerate(top_3, 1)
            ]
            exemplar_block = "\n".join(lines)
        else:
            exemplar_block = "(no similar examples available)"

        prompt = _LLM_SYSTEM_PROMPT.format(
            user_query=query,
            exemplar_block=exemplar_block,
        )

        t0 = time.monotonic()
        try:
            body = llm_call(
                {
                    "model": "llama3.1",
                    "messages": [{"role": "system", "content": prompt}],
                    "max_tokens": INTENT_LLM_MAX_TOKENS,
                    "temperature": 0.0,
                },
                timeout=120.0,
            )
            raw = body["choices"][0]["message"]["content"].strip()
            parsed = json.loads(raw)

            intent = parsed.get("intent", "semantic")
            if intent not in VALID_INTENTS:
                intent = "semantic"

            confidence = float(parsed.get("confidence", 0.5))
            slots = parsed.get("slots") or {}

            if confidence < 0.60:
                intent = "clarify_intent"

            latency_ms = int((time.monotonic() - t0) * 1000)
            log.info(
                "intent.llm",
                intent=intent,
                confidence=confidence,
                latency_ms=latency_ms,
            )
            return QueryPlan(
                strategy=INTENT_ACTIONS.get(intent, "semantic"),
                intent=intent,
                search_term=slots.get("topic"),
                confidence=confidence,
                source="llm",
                slots=slots,
            )
        except Exception:
            latency_ms = int((time.monotonic() - t0) * 1000)
            log.warning(
                "intent.llm_failed",
                latency_ms=latency_ms,
                exc_info=True,
            )
            return QueryPlan(
                strategy="semantic", intent="semantic",
                confidence=0.0, source="llm",
            )
