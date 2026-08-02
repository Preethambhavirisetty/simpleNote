"""Cross-encoder reranking from the remote inference host.

Why this exists for playbook search: these playbooks differ by *intent*, not by
topic. Every one of them is about notes, so their bi-encoder embeddings sit in
a narrow cone (measured at 0.44-0.72 cosine between playbooks) and a short
question ranks them close to arbitrarily. A cross-encoder reads the question
and the playbook description together, which is the only way that distinction
is visible.

Same Cohere-compatible endpoint the orchestrator's chat reranker uses.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Sequence

import httpx

from config import RERANKER_API_BASE, RERANKER_API_KEY, RERANKER_TIMEOUT

log = logging.getLogger(__name__)

_http: httpx.Client | None = None


@dataclass(frozen=True)
class RankedDocument:
    index: int
    score: float


class RerankerUnavailableError(RuntimeError):
    """No reranker endpoint is configured, or it could not be reached."""


def reranker_available() -> bool:
    return bool(RERANKER_API_BASE)


def _http_client() -> httpx.Client:
    global _http
    if _http is None:
        _http = httpx.Client()
    return _http


def rerank(query: str, documents: Sequence[str], top_n: int | None = None) -> list[RankedDocument]:
    """Score each document against the query, best first.

    Scores are raw cross-encoder logits, not probabilities - they are commonly
    negative and are only meaningful relative to each other in one call. Do not
    threshold them against a fixed number.
    """
    if not documents:
        return []
    if not reranker_available():
        raise RerankerUnavailableError(
            "no reranker endpoint configured: set EC2_INFERENCE_BASE_IP or "
            "RERANKER_API_BASE"
        )

    headers = {"Content-Type": "application/json"}
    if RERANKER_API_KEY:
        headers["Authorization"] = f"Bearer {RERANKER_API_KEY}"

    try:
        response = _http_client().post(
            f"{RERANKER_API_BASE}/rerank",
            headers=headers,
            json={
                "query": query,
                "documents": list(documents),
                "top_n": top_n or len(documents),
            },
            timeout=RERANKER_TIMEOUT,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise RerankerUnavailableError(
            f"rerank request to {RERANKER_API_BASE} failed: {exc}"
        ) from exc

    return _parse(response.json(), len(documents))


def _parse(payload: Any, count: int) -> list[RankedDocument]:
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        raise RerankerUnavailableError("rerank endpoint returned no results list")

    ranked: list[RankedDocument] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        # Cohere calls it relevance_score; this deployment calls it score.
        score = item.get("relevance_score", item.get("score"))
        if isinstance(index, int) and 0 <= index < count and isinstance(score, (int, float)):
            ranked.append(RankedDocument(index=index, score=float(score)))

    if not ranked:
        raise RerankerUnavailableError("rerank endpoint returned no usable results")

    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked
