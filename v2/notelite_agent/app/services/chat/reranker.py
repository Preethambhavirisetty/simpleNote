from __future__ import annotations

import logging
from typing import Any

import httpx
from llama_index.core import Document as LlamaDocument

from app.core.config import RERANKER_API_BASE, RERANKER_API_KEY


log = logging.getLogger(__name__)

_TIMEOUT = 30.0


def rerank(
    query: str,
    chunks: list[tuple[LlamaDocument, float]],
    *,
    top_k: int,
) -> list[tuple[LlamaDocument, float]]:
    """Remote cross-encoder reranking (Cohere-compatible API).

    POST {RERANKER_API_BASE}/rerank
        body:     {"query": str, "documents": [str, ...], "top_n": int}
        response: {"results": [{"index": int, "relevance_score": float}, ...]}

    Falls back to the original RRF order when unconfigured or on failure.
    """
    if not RERANKER_API_BASE or len(chunks) <= 1:
        return chunks[:top_k]

    texts = [doc.text for doc, _ in chunks]
    try:
        resp = httpx.post(
            f"{RERANKER_API_BASE}/rerank",
            json={"query": query, "documents": texts, "top_n": top_k},
            headers={"Authorization": f"Bearer {RERANKER_API_KEY}", "Content-Type": "application/json"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        results: list[dict[str, Any]] = resp.json().get("results", [])
        ranked = sorted(results, key=lambda r: r["relevance_score"], reverse=True)
        return [(chunks[r["index"]][0], r["relevance_score"]) for r in ranked[:top_k]]
    except Exception:
        log.warning("reranker failed, using RRF ranking", exc_info=True)
        return chunks[:top_k]
