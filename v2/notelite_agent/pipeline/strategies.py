"""Intent handlers — retrieval and structured facts for the chat LLM."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.contracts import AccessContext
from core.settings import init_llama_index_settings
from services.retrieval import VectorStore


@dataclass
class HandlerResult:
    response_mode: str  # rag | clarify | conversation_meta
    intent: str
    citations: list[Any] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    context: str = ""
    fact: str | None = None
    skip_context: bool = False
    used_llm: bool = False


def _vector_context(access_context: AccessContext, query: str, k: int) -> tuple[str, list[str]]:
    init_llama_index_settings()
    with VectorStore() as db:
        results = db.retrieve_documents(query, k=k, access_context=access_context)
    context = "\n\n".join(doc.text for doc in results)
    source_ids = list(dict.fromkeys(
        doc.metadata.get("note_id")
        for doc in results
        if doc.metadata.get("note_id")
    ))
    return context, source_ids


def handle_list_notes_intent(
    access_context: AccessContext,
    query: str,
    k: int,
) -> HandlerResult:
    """Structured listing — SQL path not wired; fall back to vector context."""
    ctx, ids = _vector_context(access_context, query, k)
    return HandlerResult(
        response_mode="rag", intent="list_notes", context=ctx, source_ids=ids,
    )


def handle_temporal_intent(
    access_context: AccessContext,
    query: str,
    k: int,
) -> HandlerResult:
    ctx, ids = _vector_context(access_context, query, k)
    return HandlerResult(
        response_mode="rag", intent="temporal", context=ctx, source_ids=ids,
    )


def handle_presence_check_intent(
    access_context: AccessContext,
    query: str,
    k: int,
) -> HandlerResult:
    ctx, ids = _vector_context(access_context, query, max(k, 8))
    return HandlerResult(
        response_mode="rag", intent="presence_check", context=ctx, source_ids=ids,
    )


def handle_keyword_count_intent(
    access_context: AccessContext,
    query: str,
    k: int,
) -> HandlerResult:
    ctx, ids = _vector_context(access_context, query, k)
    return HandlerResult(
        response_mode="rag", intent="keyword_count", context=ctx, source_ids=ids,
    )


def handle_corpus_stats_intent(
    access_context: AccessContext,
    query: str,
    k: int,
) -> HandlerResult:
    ctx, ids = _vector_context(access_context, query, k)
    return HandlerResult(
        response_mode="rag", intent="corpus_stats", context=ctx, source_ids=ids,
    )


def handle_semantic_intent(
    access_context: AccessContext,
    query: str,
    k: int,
) -> HandlerResult:
    ctx, ids = _vector_context(access_context, query, k)
    return HandlerResult(
        response_mode="rag", intent="semantic", context=ctx, source_ids=ids,
    )


def handle_locate_note_intent(
    access_context: AccessContext,
    query: str,
    k: int,
) -> HandlerResult:
    ctx, ids = _vector_context(access_context, query, max(k, 8))
    return HandlerResult(
        response_mode="rag", intent="locate_note", context=ctx, source_ids=ids,
    )


def handle_compare_notes_intent(
    access_context: AccessContext,
    query: str,
    k: int,
) -> HandlerResult:
    ctx, ids = _vector_context(access_context, query, max(k, 12))
    return HandlerResult(
        response_mode="rag", intent="compare_notes", context=ctx, source_ids=ids,
    )


def handle_conversation_meta_intent(
    _access_context: AccessContext,
    query: str,
    history: list[dict],
    k: int,
) -> HandlerResult:
    return HandlerResult(
        response_mode="conversation_meta",
        intent="conversation_meta",
        context="",
        used_llm=False,
    )


def handle_clarify_intent(
    _access_context: AccessContext,
    query: str,
    history: list[dict],
    k: int,
) -> HandlerResult:
    return HandlerResult(
        response_mode="clarify",
        intent="clarify_intent",
        context="",
        used_llm=False,
    )
