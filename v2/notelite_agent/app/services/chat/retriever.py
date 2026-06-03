from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.core.config import LLM_CONTEXT_WINDOW, RERANKER_API_BASE
from app.logger import logger
from app.services.chat.reranker import rerank
from app.services.ingestion.storage.vector_store import QdrantVectorStore
from app.shared.utils import count_tokens


_SUMMARY_TOP_K = 10  # notes to surface from summary-level search
_SHORT_FOLLOWUP_MAX_TERMS = 3

# Token budget for injected excerpts — leave room for output, system prompt, and history.
_CONTEXT_BUDGET = min(LLM_CONTEXT_WINDOW // 4, 8196)


def retrieve_context(
    vector_store: QdrantVectorStore,
    query: str,
    user_id: str,
    k: int,
    role: str,
    history: Sequence[Mapping[str, str]] | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Return selected context excerpts and UI references for chat streaming."""
    context_texts, references, _ = retrieve_context_diagnostics(
        vector_store, query, user_id, k, role, history,
    )
    return context_texts, references


def retrieve_context_diagnostics(
    vector_store: QdrantVectorStore,
    query: str,
    user_id: str,
    k: int,
    role: str,
    history: Sequence[Mapping[str, str]] | None = None,
) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
    """Run the retrieval pipeline and return inspectable intermediate outputs."""
    metadata_filter = None if role == "admin" else {"user_id": user_id}
    search_query = contextualize_retrieval_query(query, history)

    summary_hits = _search_summaries(vector_store, search_query, metadata_filter)
    doc_ids = _doc_ids(summary_hits)
    chunk_hits = _search_chunks(vector_store, search_query, k, metadata_filter, doc_ids)
    ranked_hits = rerank(search_query, chunk_hits, top_k=k)
    context_texts, references, remaining_budget = _select_context(ranked_hits)

    diagnostics = _diagnostics(
        query=query,
        search_query=search_query,
        metadata_filter=metadata_filter,
        summary_hits=summary_hits,
        doc_ids=doc_ids,
        chunk_hits=chunk_hits,
        ranked_hits=ranked_hits,
        context_texts=context_texts,
        references=references,
        remaining_budget=remaining_budget,
    )
    _log_diagnostics(diagnostics)
    return context_texts, references, diagnostics


def contextualize_retrieval_query(
    query: str,
    history: Sequence[Mapping[str, str]] | None,
) -> str:
    """Add the latest exchange to retrieval-only searches for terse follow-ups."""
    if len(re.findall(r"\w+", query)) > _SHORT_FOLLOWUP_MAX_TERMS or not history:
        return query

    recent_messages = []
    for message in reversed(history):
        if message.get("role") not in {"user", "assistant"}:
            continue
        content = (message.get("content") or "").strip()
        if content:
            recent_messages.append(content)
        if len(recent_messages) == 2:
            break

    if not recent_messages:
        return query
    return "\n".join([*reversed(recent_messages), query])


def _search_summaries(
    vector_store: QdrantVectorStore,
    search_query: str,
    metadata_filter: Mapping[str, Any] | None,
) -> list[tuple[Any, float]]:
    # Dense-only is intentional: summaries capture whole-note meaning.
    return vector_store.search_summaries(
        search_query,
        limit=_SUMMARY_TOP_K,
        metadata_filter=metadata_filter,
    )


def _doc_ids(summary_hits: Sequence[tuple[Any, float]]) -> list[str]:
    return [
        doc.metadata["doc_id"]
        for doc, _score in summary_hits
        if doc.metadata.get("doc_id")
    ]


def _search_chunks(
    vector_store: QdrantVectorStore,
    search_query: str,
    k: int,
    metadata_filter: Mapping[str, Any] | None,
    doc_ids: Sequence[str],
) -> list[tuple[Any, float]]:
    if doc_ids:
        return vector_store.search_chunks(
            search_query,
            limit=k * 2,  # extra candidates for the reranker to pick from
            metadata_filter=metadata_filter,
            doc_ids=doc_ids,
        )
    return vector_store.search_chunks(
        search_query,
        limit=k,
        metadata_filter=metadata_filter,
    )


def _select_context(
    ranked_hits: Sequence[tuple[Any, float]],
) -> tuple[list[str], list[dict[str, Any]], int]:
    context_texts: list[str] = []
    references: list[dict[str, Any]] = []
    references_by_note_id: dict[str, dict[str, Any]] = {}
    token_budget = _CONTEXT_BUDGET

    for doc, _score in ranked_hits:
        text = doc.text.strip()
        if not text:
            continue
        chunk_tokens = count_tokens(text)
        if chunk_tokens > token_budget:
            break

        context_texts.append(text)
        _add_reference(references, references_by_note_id, _reference_payload(doc))
        token_budget -= chunk_tokens

    return context_texts, references, token_budget


def _add_reference(
    references: list[dict[str, Any]],
    references_by_note_id: dict[str, dict[str, Any]],
    reference: dict[str, Any],
) -> None:
    note_id = reference.get("note_id")
    if not note_id:
        return

    existing_reference = references_by_note_id.get(note_id)
    if existing_reference:
        for chunk_id in reference["chunk_ids"]:
            if chunk_id not in existing_reference["chunk_ids"]:
                existing_reference["chunk_ids"].append(chunk_id)
        return

    references.append(reference)
    references_by_note_id[note_id] = reference


def _diagnostics(
    *,
    query: str,
    search_query: str,
    metadata_filter: Mapping[str, Any] | None,
    summary_hits: Sequence[tuple[Any, float]],
    doc_ids: Sequence[str],
    chunk_hits: Sequence[tuple[Any, float]],
    ranked_hits: Sequence[tuple[Any, float]],
    context_texts: list[str],
    references: list[dict[str, Any]],
    remaining_budget: int,
) -> dict[str, Any]:
    source_ids = [reference["note_id"] for reference in references]
    return {
        "query": query,
        "search_query": search_query,
        "contextualized_followup": search_query != query,
        "metadata_filter": metadata_filter,
        "summary_hits": [_hit_payload(doc, score) for doc, score in summary_hits],
        "summary_doc_ids": list(doc_ids),
        "chunk_search_scope": "summary_doc_ids" if doc_ids else "all_user_chunks",
        "chunk_hits": [_hit_payload(doc, score) for doc, score in chunk_hits],
        "reranker_enabled": bool(RERANKER_API_BASE),
        "reranked_hits": [_hit_payload(doc, score) for doc, score in ranked_hits],
        "selected_context": context_texts,
        "source_ids": source_ids,
        "references": references,
        "context_budget_tokens": _CONTEXT_BUDGET,
        "remaining_context_budget_tokens": remaining_budget,
    }


def _log_diagnostics(diagnostics: Mapping[str, Any]) -> None:
    logger.info(
        "retrieval.completed",
        summary_hit_count=len(diagnostics["summary_hits"]),
        chunk_hit_count=len(diagnostics["chunk_hits"]),
        reranked_hit_count=len(diagnostics["reranked_hits"]),
        selected_context_count=len(diagnostics["selected_context"]),
        source_count=len(diagnostics["source_ids"]),
        remaining_context_budget_tokens=diagnostics["remaining_context_budget_tokens"],
        context_budget_tokens=diagnostics["context_budget_tokens"],
        fallback_to_all_chunks=not bool(diagnostics["summary_doc_ids"]),
        reranker_enabled=diagnostics["reranker_enabled"],
        chunk_search_scope=diagnostics["chunk_search_scope"],
        contextualized_followup=diagnostics["contextualized_followup"],
    )


def _reference_payload(doc: Any) -> dict[str, Any]:
    metadata = doc.metadata or {}
    chunk_id = metadata.get("chunk_id")
    return {
        "note_id": str(metadata.get("note_id") or ""),
        "folder_id": str(metadata.get("folder_id") or ""),
        "title": str(metadata.get("note_title") or "Untitled"),
        "folder": str(metadata.get("folder_title") or ""),
        "chunk_ids": [str(chunk_id)] if chunk_id else [],
    }


def _hit_payload(doc: Any, score: float) -> dict[str, Any]:
    return {
        "id": str(doc.id_),
        "doc_id": doc.metadata.get("doc_id"),
        "note_id": doc.metadata.get("note_id"),
        "chunk_id": doc.metadata.get("chunk_id"),
        "score": score,
        "text": doc.text,
    }
