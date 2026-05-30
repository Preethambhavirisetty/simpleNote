from __future__ import annotations

import logging
from typing import Any

from app.core.config import LLM_CONTEXT_WINDOW, RERANKER_API_BASE
from app.services.chat.reranker import rerank
from app.services.ingestion.storage.vector_store import QdrantVectorStore
from app.shared.utils import count_tokens


log = logging.getLogger(__name__)

_SUMMARY_TOP_K = 5  # notes to surface from summary-level search

# Token budget for injected excerpts — leave room for output, system prompt, and history.
_CONTEXT_BUDGET = min(LLM_CONTEXT_WINDOW // 4, 8196)


def retrieve_context(
    vector_store: QdrantVectorStore,
    query: str,
    user_id: str,
    k: int,
    role: str,
) -> tuple[list[str], list[str]]:
    """Two-stage hybrid retrieval with optional cross-encoder reranking.

    Stage 1 — Summary search (dense only):
        Dense search on the summary collection identifies the most relevant
        notes by semantic topic. Dense-only is intentional: summaries capture
        the meaning of a whole note; BM42 at this level would bias toward
        keyword overlap rather than topical relevance.

    Stage 2 — Chunk search (dense + BM42 sparse, RRF fusion):
        Hybrid search scoped to the doc_ids from stage 1. Dense handles
        semantic similarity; BM42 sparse handles keyword precision (e.g.
        exact names, dates). RRF fuses both rankings.
        Falls back to a full-user chunk search when stage 1 yields nothing.

    Stage 3 — Reranking:
        Remote cross-encoder (Cohere-compatible) if RERANKER_API_BASE is set;
        otherwise the RRF scores from Qdrant are used as-is.

    Returns (context_texts, source_ids) respecting the token budget.
    """
    context_texts, source_ids, _ = retrieve_context_diagnostics(
        vector_store, query, user_id, k, role,
    )
    return context_texts, source_ids


def retrieve_context_diagnostics(
    vector_store: QdrantVectorStore,
    query: str,
    user_id: str,
    k: int,
    role: str,
) -> tuple[list[str], list[str], dict[str, Any]]:
    """Run retrieval and return its inspectable intermediate outputs."""
    metadata_filter = None if role == "admin" else {"user_id": user_id}

    # Stage 1: find the most relevant notes via summary-level dense search
    summary_hits = vector_store.search_summaries(
        query, limit=_SUMMARY_TOP_K, metadata_filter=metadata_filter,
    )
    doc_ids = [
        doc.metadata["doc_id"]
        for doc, _ in summary_hits
        if doc.metadata.get("doc_id")
    ]

    # Stage 2: hybrid chunk search scoped to those notes (or fallback to all)
    if doc_ids:
        chunk_hits = vector_store.search_chunks(
            query,
            limit=k * 2,  # extra candidates for the reranker to pick from
            metadata_filter=metadata_filter,
            doc_ids=doc_ids,
        )
    else:
        chunk_hits = vector_store.search_chunks(
            query,
            limit=k,
            metadata_filter=metadata_filter,
        )

    # Stage 3: rerank (remote cross-encoder or RRF fallback)
    ranked = rerank(query, chunk_hits, top_k=k)

    # Apply token budget
    context_texts: list[str] = []
    source_ids: list[str] = []
    token_budget = _CONTEXT_BUDGET

    for doc, _score in ranked:
        text = doc.text.strip()
        if not text:
            continue
        chunk_tokens = count_tokens(text)
        if chunk_tokens > token_budget:
            break
        context_texts.append(text)
        source_ids.append(str(doc.id_))
        token_budget -= chunk_tokens

    diagnostics = {
        "query": query,
        "metadata_filter": metadata_filter,
        "summary_hits": [_hit_payload(doc, score) for doc, score in summary_hits],
        "summary_doc_ids": doc_ids,
        "chunk_search_scope": "summary_doc_ids" if doc_ids else "all_user_chunks",
        "chunk_hits": [_hit_payload(doc, score) for doc, score in chunk_hits],
        "reranker_enabled": bool(RERANKER_API_BASE),
        "reranked_hits": [_hit_payload(doc, score) for doc, score in ranked],
        "selected_context": context_texts,
        "source_ids": source_ids,
        "context_budget_tokens": _CONTEXT_BUDGET,
        "remaining_context_budget_tokens": token_budget,
    }
    return context_texts, source_ids, diagnostics


def _hit_payload(doc: Any, score: float) -> dict[str, Any]:
    return {
        "id": str(doc.id_),
        "doc_id": doc.metadata.get("doc_id"),
        "score": score,
        "text": doc.text,
    }
