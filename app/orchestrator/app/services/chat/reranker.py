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

# The cross-encoder behind /rerank is a 512-token model, and the server answers
# 500 rather than truncating an over-long document. One long chunk in the
# candidate set therefore failed the whole request, and the silent RRF fallback
# below turned that into "reranking is off" for every query that happened to
# retrieve a long note - measured: scores dropped from 1.3-5.7 to 0.03-0.05 the
# moment a 1,849-character chunk entered the corpus.
#
# Measured empirically against the deployed model: 1,200 characters succeed and
# 1,500 fail. 1,000 leaves headroom, and costs nothing - the model only reads
# its first 512 tokens, so the truncated tail was never scored anyway.
RERANK_MAX_DOCUMENT_CHARS = 1000

# Documents per request. Keeps one request bounded and lets a single failing
# batch degrade to RRF for that batch alone rather than for the whole query.
RERANK_BATCH_SIZE = 16

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

    scored: list[dict[str, int | float]] = []
    failed_batches = 0

    for start in range(0, len(chunks), RERANK_BATCH_SIZE):
        batch = chunks[start : start + RERANK_BATCH_SIZE]
        try:
            scored.extend(
                {"index": start + result["index"], "score": result["score"]}
                for result in _rerank_batch(query, batch)
            )
        except Exception:
            failed_batches += 1
            log.warning(
                "reranker batch failed, keeping RRF order for it",
                extra={"batch_start": start, "batch_size": len(batch)},
                exc_info=True,
            )

    if not scored:
        log.warning("reranker unusable for this query, using RRF ranking")
        return chunks[:top_k]

    # Ordering and filtering are separate jobs, and this model is only reliable
    # at the first. ms-marco returns negative logits for correct matches -
    # measured here, "sourdough" scores its own starter log at -11.0 and still
    # ranks it first, "baking" scores the right note -2.66 at the top. Dropping
    # everything below zero therefore discarded a correct ranking and fell back
    # to RRF, which is strictly worse than a negatively-scored correct order.
    #
    # So the threshold now only trims a tail that something already passed; it
    # can never empty the list or discard the reranker's ordering.
    ranked = sorted(scored, key=lambda result: result["score"], reverse=True)
    above = [result for result in ranked if result["score"] >= RERANKER_MIN_RELEVANCE_SCORE]
    if above:
        ranked = above
    else:
        log.debug(
            "no candidate cleared the relevance threshold; keeping reranked order",
            extra={"best_score": ranked[0]["score"]},
        )
    reranked = [(chunks[result["index"]][0], result["score"]) for result in ranked[:top_k]]

    if failed_batches:
        # Some candidates were never scored. Append them behind everything that
        # was, so a batch failure loses ranking quality but never a candidate.
        seen = {id(document) for document, _ in reranked}
        for document, rrf_score in chunks:
            if len(reranked) >= top_k:
                break
            if id(document) not in seen:
                reranked.append((document, rrf_score))
    return reranked


def _rerank_batch(
    query: str, batch: list[tuple[LlamaDocument, float]]
) -> list[dict[str, int | float]]:
    """Score one batch, truncating documents to what the model can accept."""
    texts = [(doc.text or "")[:RERANK_MAX_DOCUMENT_CHARS] for doc, _ in batch]
    resp = _http_client().post(
        f"{RERANKER_API_BASE}/rerank",
        json={"query": query, "documents": texts, "top_n": len(texts)},
        headers={
            "Authorization": f"Bearer {RERANKER_API_KEY}",
            "Content-Type": "application/json",
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return _valid_results(resp.json().get("results", []), len(batch))


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
