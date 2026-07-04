from __future__ import annotations

import logging
from typing import Any

import httpx
from llama_index.core import Document as LlamaDocument

from app.core.config import (
    RERANKER_API_BASE,
    RERANKER_API_KEY,
    RERANKER_MIN_RELEVANCE_SCORE,
)


log = logging.getLogger(__name__)

_TIMEOUT = 30.0

# Shared connection pool; the timeout is passed per request.
_http: httpx.Client | None = None


def _http_client() -> httpx.Client:
    global _http
    if _http is None:
        _http = httpx.Client()
    return _http


def rerank(
    query: str,
    chunks: list[tuple[LlamaDocument, float]],
    *,
    top_k: int,
) -> list[tuple[LlamaDocument, float]]:
    """Remote cross-encoder reranking (Cohere-compatible API).

    POST {RERANKER_API_BASE}/rerank
        body:     {"query": str, "documents": [str, ...], "top_n": int}
        response: {"results": [{"index": int, "relevance_score" | "score": float}, ...]}

    Results below the configured relevance threshold are discarded. Falls back
    to the original RRF order when unconfigured, on failure, or when no result
    meets the threshold.
    """
    if not RERANKER_API_BASE or len(chunks) <= 1:
        return chunks[:top_k]

    texts = [doc.text for doc, _ in chunks]
    try:
        resp = _http_client().post(
            f"{RERANKER_API_BASE}/rerank",
            json={"query": query, "documents": texts, "top_n": top_k},
            headers={"Authorization": f"Bearer {RERANKER_API_KEY}", "Content-Type": "application/json"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        results = _valid_results(resp.json().get("results", []), len(chunks))
        relevant = [
            result
            for result in results
            if result["score"] >= RERANKER_MIN_RELEVANCE_SCORE
        ]
        if not relevant:
            log.info(
                "reranker found no candidates above relevance threshold; using RRF ranking"
            )
            return chunks[:top_k]

        ranked = sorted(relevant, key=lambda result: result["score"], reverse=True)
        return [
            (chunks[result["index"]][0], result["score"])
            for result in ranked[:top_k]
        ]
    except Exception:
        log.warning("reranker failed, using RRF ranking", exc_info=True)
        return chunks[:top_k]


def _valid_results(results: Any, chunk_count: int) -> list[dict[str, int | float]]:
    valid: list[dict[str, int | float]] = []
    if not isinstance(results, list):
        return valid

    for result in results:
        if not isinstance(result, dict):
            continue

        index = result.get("index")
        score = result.get("relevance_score", result.get("score"))
        if (
            isinstance(index, int)
            and 0 <= index < chunk_count
            and isinstance(score, (int, float))
        ):
            valid.append({"index": index, "score": float(score)})

    return valid
