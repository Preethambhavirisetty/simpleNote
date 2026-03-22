import re
import numpy as np
from dataclasses import dataclass


AGGREGATION_PATTERN = re.compile(
    r'\b(how many|how much|count|total\s+number|summarize|give\s+(?:me\s+)?(?:a\s+)?summary)\b',
    re.IGNORECASE,
)

STOP_WORDS = frozenset({
    'the', 'a', 'an', 'in', 'at', 'of', 'to', 'for', 'is', 'was',
    'my', 'me', 'i', 'and', 'or', 'on', 'with', 'all', 'do', 'did',
})


@dataclass
class Intent:
    query_type: str
    knowledge_filter: dict | None
    boost_summary: bool
    detected_type: str | None
    confidence: float


class QueryProcessor:
    """Lightweight query intent processor that routes queries to the right chunks.

    Two-tier knowledge type detection:
      1. Keyword match against knowledge type names (fast, precise)
      2. Embedding similarity fallback (handles synonyms and paraphrases)
    """

    def __init__(self, embedder, knowledge_types):
        self._embedder = embedder
        self._knowledge_types = knowledge_types

        self._type_keywords = {
            kt: [w for w in kt.lower().split('_') if len(w) > 2 and w not in STOP_WORDS]
            for kt in knowledge_types
        }

        descriptions = [kt.replace('_', ' ') for kt in knowledge_types]
        self._type_embeddings = [
            (kt, np.array(self._embedder.embed_query(desc)))
            for kt, desc in zip(knowledge_types, descriptions)
        ]

    def _is_aggregation(self, query):
        return bool(AGGREGATION_PATTERN.search(query))

    def _detect_knowledge_type(self, query):
        q_lower = query.lower()

        best_match = None
        best_count = 0
        for kt, keywords in self._type_keywords.items():
            hits = sum(1 for kw in keywords if kw in q_lower)
            if hits > best_count:
                best_count = hits
                best_match = kt

        if best_match and best_count > 0:
            return best_match, 1.0

        query_emb = np.array(self._embedder.embed_query(query))
        scores = []
        for kt, type_emb in self._type_embeddings:
            cosine = float(np.dot(query_emb, type_emb) / (
                np.linalg.norm(query_emb) * np.linalg.norm(type_emb) + 1e-10
            ))
            scores.append((kt, cosine))

        scores.sort(key=lambda x: x[1], reverse=True)
        best_type, best_score = scores[0]

        if best_score < 0.5:
            return None, best_score

        if len(scores) > 1 and best_score - scores[1][1] < 0.05:
            return None, best_score

        return best_type, best_score

    def process(self, query):
        is_agg = self._is_aggregation(query)
        knowledge_type, confidence = self._detect_knowledge_type(query)

        knowledge_filter = None
        if knowledge_type:
            knowledge_filter = {"knowledge_type": knowledge_type}

        return Intent(
            query_type="aggregation" if is_agg else "factual",
            knowledge_filter=knowledge_filter,
            boost_summary=is_agg,
            detected_type=knowledge_type,
            confidence=confidence,
        )
