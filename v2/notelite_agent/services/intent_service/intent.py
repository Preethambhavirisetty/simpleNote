"""Two-tier intent detection: classifier → LLM fallback.

Layer 1 (Classifier):  Sentence-transformer embeddings + LogisticRegression head.
                       Returns intent + calibrated confidence.  Falls through if
                       conf < threshold or model not trained yet.
Layer 2 (LLM):         Structured LLM classification with few-shot context from
                       the Qdrant exemplar bank (when available).

If both tiers fail or are disabled, defaults to ``semantic``.
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

INTENT_ACTIONS: dict[str, str] = {
    "semantic":          "semantic",
    "locate_note":       "semantic",
    "list_notes":        "listing",
    "keyword_count":     "keyword_count",
    "temporal":          "temporal",
    "presence_check":    "presence_check",
    "compare_notes":     "semantic",
    "corpus_stats":      "corpus_stats",
    "conversation_meta": "conversation_meta",
    "clarify_intent":    "clarify_intent",
}

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
    source: str = "classifier"
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
            for text in texts:
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
                collection_name=INTENT_COLLECTION,
                points=points[i : i + batch_size],
            )
        log.info("intent_store.ingested", count=len(points), source=source)
        return len(points)

    def search_best_per_intent(
        self, query: str, *, fetch_limit: int = 50,
    ) -> list[tuple[str, str, float]]:
        """Return the single best-scoring exemplar per intent, sorted desc.

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


_intent_store: IntentStore | None = None


def get_intent_store() -> IntentStore | None:
    """Return a shared IntentStore (lazy singleton).

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
- semantic: Understand, recall, or summarize note CONTENT. User wants insight, meaning, or a recap. \
("what did I write about", "summarize", "explain", "what are my thoughts on", "any gems in", "anything worth rereading", "any actionable stuff")
- locate_note: Find a SPECIFIC note, or find WHERE a note/folder is stored. Includes notes about a SPECIFIC EVENT \
("the note about", "that one about", "which note has", "where is", "which folder has/stores/contains X", "the notes about the [event]", "the notes I made during the [event]")
- list_notes: Enumerate MULTIPLE notes matching a GENERAL topic, tag, or folder. The topic is a CATEGORY, not a specific event. \
("all notes about cooking", "everything tagged work", "list my travel notes", "every note", bare topic like "recipes")
- keyword_count: Get a NUMBER — how many notes mention X, or how frequently. Quantity words like "many", "a lot", "how much". \
("how many notes mention", "count", "how often", "are there many notes on X", "do I have a lot of notes about X")
- temporal: Notes filtered primarily by TIME ("last week", "yesterday", "in March", "latest", "when did I write")
- presence_check: Simple YES/NO existence check — does a note exist on a topic? The answer is strictly "yes" or "no". \
No quantity (that's keyword_count), no content retrieval (that's semantic), no finding it (that's locate_note). \
("did I ever write about X", "is there a note about X", "have I mentioned X", "do I have anything on X"). \
NOT "are there many" (keyword_count), NOT "any insights/gems/actionable stuff" (semantic).
- compare_notes: Compare, contrast, or find DIFFERENCES/SIMILARITIES between two or more specific notes or topics. \
Requires at least two subjects being weighed against each other. \
("compare my notes on X and Y", "differences between X and Y", "what changed between draft A and B", \
"is there more about X or Y", "are X and Y notes consistent", "do I write more about X or Y")
- corpus_stats: Metadata/statistics about the entire COLLECTION — total counts, sizes, structure. NOT about finding a specific folder. \
("how many notes total", "largest note", "total word count", "most recently edited note")
- conversation_meta: About THIS CHAT CONVERSATION or closers ("what did I ask you", "repeat that", "say that again", "thanks", "bye", "nope that's not what I meant")
- clarify_intent: Query is AMBIGUOUS, requests a NON-RETRIEVAL ACTION the app cannot perform, or COMBINES MULTIPLE conflicting intents. \
Use when: (1) query is too vague to determine intent ("stuff", "help", single word with no verb), \
(2) user asks to delete/edit/export/share/move/merge/duplicate/rename — these are write actions, not retrieval, \
(3) query chains two distinct intents ("show me X and also compare Y", "list X then count Y"), \
(4) query references an action + a destructive modifier ("find X and then delete it"). \
("delete my notes", "export to PDF", "merge these two", "show me X and also compare Y", "find X and then delete the old one")

## Decision Rules:
1. Time reference + understanding goal → semantic, NOT temporal
2. "the [specific event/thing]" (renovation, conference, move, plumber) → locate_note, even if "notes" is plural. A specific event is not a general category.
3. "which folder has/stores/contains X" or "where do I keep X" → locate_note, NOT corpus_stats. User wants to FIND something.
4. "are there many", "do I have a lot of", "how much" + topic → keyword_count, NOT presence_check. User wants quantity.
5. "any [qualifier] stuff/gems/insights" where user seeks content understanding → semantic, NOT presence_check. User wants to explore content.
6. Non-retrieval actions (delete, rename, move, edit, export, share) → clarify_intent
7. Query combines two distinct intents with "and also", "then", "plus" → clarify_intent
8. When uncertain between intents, prefer semantic

## User Query:
"{user_query}"

Respond with ONLY valid JSON:
{{"intent": "<intent_name>", "confidence": 0.0-1.0, "slots": {{"topic": null, "time_range": null, "scope": null}}, "reasoning": "<one sentence>"}}"""


# ── QueryPlanner ─────────────────────────────────────────────────────────


class QueryPlanner:
    """Two-tier intent classifier: trained classifier -> LLM fallback."""

    def plan(self, query: str) -> QueryPlan:
        # Layer 1: trained classifier
        if is_enabled("chat.intent_classifier"):
            plan = self._try_classifier(query)
            if plan is not None:
                return plan

        # Gather exemplar context for LLM few-shot (best-effort, never blocks)
        exemplar_results: list[tuple[str, str, float]] = []
        if is_enabled("chat.intent_exemplar"):
            store = get_intent_store()
            if store is not None:
                exemplar_results = store.search_best_per_intent(query)

        # Layer 2: LLM fallback
        if is_enabled("chat.intent_llm"):
            return self._try_llm(query, exemplar_results)

        # All tiers exhausted — safe default
        log.info("intent.default_fallback", query=query[:80])
        return QueryPlan(
            strategy="semantic", intent="semantic",
            confidence=0.0, source="default",
        )

    # ── Layer 1: trained classifier ───────────────────────────────────

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
        except Exception:
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

        log.info("intent.classifier", intent=intent, confidence=confidence)
        return QueryPlan(
            strategy=INTENT_ACTIONS.get(intent, "semantic"),
            intent=intent,
            confidence=confidence,
            source="classifier",
        )

    # ── Layer 2: LLM fallback ─────────────────────────────────────────

    @staticmethod
    def _try_llm(
        query: str,
        exemplar_results: list[tuple[str, str, float]],
    ) -> QueryPlan:
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
