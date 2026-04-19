"""Three-tier intent detection: regex → classifier → LLM fallback.

Layer 0 (Regex):       Catches obvious patterns (corpus_stats, conversation_meta,
                       keyword_count, temporal, list_notes, etc.) with zero latency.
Layer 1 (Classifier):  Sentence-transformer embeddings + LogisticRegression head.
                       Returns intent + calibrated confidence.  Falls through if
                       conf < threshold or model not trained yet.
Layer 1b (Exemplar):   Legacy fallback — Qdrant exemplar similarity.  Used only
                       when the classifier is unavailable.
Layer 2 (LLM):         Structured LLM classification with few-shot context.
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
from services.intent_service.regex_rules import _REGEX_RULES

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

EXEMPLAR_HIGH_THRESHOLD = 0.78
EXEMPLAR_AGREE_THRESHOLD = 0.68

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
        batch_size = 100
        for i in range(0, len(points), batch_size):
            self._client.upsert(
                collection_name=INTENT_COLLECTION, points=points[i:i + batch_size],
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

# ── LLM classification prompt ───────────────────────────────────────────

_LLM_SYSTEM_PROMPT = """\
You are an intent classifier for a personal notes app. Classify the user's query into exactly one intent.

## Similar Examples from Database:
{exemplar_block}

## Intents:
- semantic: Understand, recall, or summarize note CONTENT ("what did I write about", "summarize", "explain")
- locate_note: Find ONE SPECIFIC note ("which note has", "where is", "the note about", "that one about")
- list_notes: Enumerate MULTIPLE notes matching a filter ("all notes about", "everything tagged", "list", "every note")
- keyword_count: Get a NUMBER — occurrences or note counts ("how many", "count", "how often")
- temporal: Notes filtered primarily by TIME ("last week", "yesterday", "in March", "latest", "when did I")
- presence_check: YES/NO existence check ("did I ever", "do I have anything about", "is there a note", "any note about")
- compare_notes: Compare or contrast two+ notes/topics ("compare", "differences", "what changed", "contradictions")
- corpus_stats: Metadata/statistics about the collection, not content ("how many notes total", "largest note", "empty folders")
- conversation_meta: About THIS CONVERSATION or closers ("what did I ask you", "repeat that", "thanks", "bye")
- clarify_intent: Query is ambiguous, a non-retrieval action (delete/edit/move), or combines conflicting intents

## Decision Rules:
1. Time reference + understanding goal → semantic, NOT temporal
2. "the note" (singular specific) → locate_note, NOT list_notes
3. Answer is yes/no → presence_check, even if time is mentioned
4. Non-retrieval actions (delete, rename, move, edit) → clarify_intent
5. When uncertain, prefer semantic over other intents

## User Query:
"{user_query}"

Respond with ONLY valid JSON:
{{"intent": "<intent_name>", "confidence": 0.0-1.0, "slots": {{"topic": null, "time_range": null, "scope": null}}, "reasoning": "<one sentence>"}}"""

# _LLM_SYSTEM_PROMPT = """\
# You are an intent classifier for a personal notes app.

# ## User's Query:
# "{user_query}"

# ## Most Similar Known Examples (from our database):
# {exemplar_block}

# ## Available Intents (read descriptions carefully):
# - semantic: User wants to UNDERSTAND, RECALL, or SUMMARIZE note content. \
# Signals: "what did I write about", "tell me about", "summarize", "explain my notes on". \
# Use when the user wants insight or comprehension, not just finding/listing.
# - locate_note: User wants to find ONE SPECIFIC note or item. \
# Signals: "the note", "that note", "the one about", "which note has", "where is", "find the". \
# Key: SINGULAR reference to a specific document.
# - list_notes: User wants to ENUMERATE or LIST MULTIPLE notes matching a topic or filter. \
# Signals: "all notes", "everything about", "every note", "list", "show me notes about". \
# Key: PLURAL, wants a collection of results.
# - keyword_count: User wants a NUMBER — how many times a word/phrase appears or how many notes mention it. \
# Signals: "how many", "count", "how often", "number of".
# - temporal: User wants notes filtered by TIME — when something was written, or notes from a date range. \
# Signals: "last week", "yesterday", "in March", "most recent", "when did I", "latest". \
# Key: a time expression is the PRIMARY filter.
# - presence_check: User wants a YES/NO answer about whether something EXISTS in their notes. \
# Signals: "did I ever", "do I have anything about", "is there a note", "have I mentioned", "any note about". \
# Key: the answer is fundamentally yes or no.
# - compare_notes: User wants to COMPARE, CONTRAST, or find DIFFERENCES between two or more notes/topics. \
# Signals: "compare", "differences between", "contrast", "what changed", "consistent", "contradictions".
# - corpus_stats: User wants METADATA/STATISTICS about their note collection, not content. \
# Signals: "how many notes do I have", "largest note", "empty folders", "total word count", "breakdown per folder".
# - conversation_meta: User is referring to THIS CONVERSATION, not their notes. \
# Signals: "what did I ask you", "repeat that", "say that again", "thanks", "bye", "that's all".
# - clarify_intent: The query is TOO AMBIGUOUS to classify. Use this when: \
# (1) the query is a single word or fragment with no clear intent (e.g. "notes", "help"), \
# (2) the query is an ACTION REQUEST that is not retrieval (e.g. "delete my notes", "organize my folders"), \
# (3) the query combines MULTIPLE INTENTS that conflict (e.g. "list X and also count Y"), or \
# (4) you genuinely cannot determine what the user wants.

# ## Rules:
# - Pick the SINGLE best intent based on the PRIMARY purpose of the query.
# - If a query has a time reference but the main goal is recall/understanding, pick semantic, not temporal.
# - If a query mentions "the note" (singular, specific), pick locate_note, not list_notes.
# - If the answer would be yes/no, pick presence_check, even if a time reference is present.
# - Do NOT hesitate to return clarify_intent for genuinely ambiguous or non-retrieval queries.

# Respond with ONLY a JSON object, nothing else:
# {{"intent": "<intent_name>", "confidence": 0.0-1.0, "slots": {{"topic": null, "time_range": null, "scope": null}}, "reasoning": "<one sentence>"}}"""


# ── QueryPlanner ─────────────────────────────────────────────────────────


class QueryPlanner:
    """Three-tier intent classifier: regex → SetFit classifier → LLM fallback."""

    def plan(self, query: str) -> QueryPlan:
        # Layer 0: regex fast-path
        # plan = self._try_regex(query)
        # if plan is not None:
        #     return plan

        # Layer 1: SetFit classifier (replaces exemplar similarity)
        if is_enabled("chat.intent_classifier"):
            plan = self._try_classifier(query)
            if plan is not None:
                return plan

        # Fetch exemplar results once (shared between fallback tiers)
        exemplar_results: list[tuple[str, str, float]] = []
        if is_enabled("chat.intent_exemplar"):
            store = get_intent_store()
            if store is not None:
                exemplar_results = store.search_best_per_intent(query)

        # Layer 1 fallback: exemplar similarity (used when classifier not available)
        plan = self._evaluate_exemplars(exemplar_results)
        if plan is not None:
            return plan

        # Layer 2: LLM fallback
        if is_enabled("chat.intent_llm"):
            return self._try_llm(query, exemplar_results)

    # "confidence": result["confidence"],  # ← actual classifier confidence
    # "method": "default_fallback",
    # "original_prediction": result["intent"],

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

    # ── Layer 1: SetFit classifier ──────────────────────────────────

    @staticmethod
    def _try_classifier(query: str) -> QueryPlan | None:
        """Run query through the trained classifier."""
        try:
            from services.intent_service.classifier import (
                CONFIDENCE_THRESHOLD,
                IntentClassifier,
                append_low_confidence,
            )
            clf = IntentClassifier.load()
        except (FileNotFoundError, Exception):
            log.debug("intent.classifier_unavailable", exc_info=True)
            return None

        intent, confidence = clf.predict(query)

        if confidence < CONFIDENCE_THRESHOLD:
            log.info(
                "intent.classifier_low_conf",
                intent=intent, confidence=confidence,
            )
            append_low_confidence(query, intent, confidence)
            return None

        log.info(
            "intent.classifier",
            intent=intent, confidence=confidence,
        )
        return QueryPlan(
            strategy=INTENT_ACTIONS.get(intent, "semantic"),
            intent=intent,
            confidence=confidence,
            source="classifier",
        )

    # ── Layer 1 fallback: exemplar similarity ────────────────────────

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
            json_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not json_match:
                raise ValueError("No JSON object in LLM response")
            parsed = json.loads(json_match.group())

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
