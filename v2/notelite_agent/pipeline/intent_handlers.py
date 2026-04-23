"""Intent-specific retrieval handlers.

Routes each intent to the minimal retrieval path it needs:

    Short-circuit (no note retrieval):
        clarify_intent, conversation_meta

    Scroll-only (full chunk scan, no vector search):
        keyword_count, temporal, listing, presence_check, corpus_stats

    Vector search (summary → chunk → soft score → rerank → LLM):
        semantic, locate_note, compare_notes
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import structlog

from core.contracts import AccessContext
from pipeline.intent import QueryPlan
from pipeline.llm import llm_call
from pipeline.strategies import execute as execute_strategy
from services.retrieval import VectorStore

log = structlog.get_logger()

_SCROLL_ONLY_STRATEGIES = frozenset({
    "keyword_count", "temporal", "listing", "presence_check", "corpus_stats",
})

_CLARIFY_GENERIC = (
    "I'm not sure what you're looking for. Could you ask a specific "
    "question about your notes? For example:\n"
    '- "What did I write about project X?"\n'
    '- "List all my notes about travel"\n'
    '- "How many times did I mention budgeting?"'
)

_CLARIFY_SYSTEM = (
    "The user sent an ambiguous query to a personal notes assistant. "
    "Based on the conversation so far, generate ONE short clarifying "
    "question (1-2 sentences) that helps narrow down what they want "
    "from their notes. Do NOT answer the query — only ask for clarification."
)

_CONVERSATION_META_SYSTEM = (
    "You are a personal notes assistant. The user is asking about "
    "this conversation, not their notes. Answer based on the "
    "conversation history below. If they are saying goodbye, "
    "respond warmly and briefly."
)


@dataclass
class HandlerResult:
    """Unified result from intent handling.

    If ``answer`` is set, the chat endpoint uses it directly and skips the
    main RAG LLM call.  Otherwise ``context`` / ``fact`` / ``skip_context``
    feed into the standard prompt-building path.
    """
    answer: str | None = None
    context: str = ""
    fact: str | None = None
    source_ids: list[str] = field(default_factory=list)
    skip_context: bool = False
    retrieval_ms: int = 0
    strategy_ms: int = 0
    inference_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tokens_used: int = 0


def handle_intent(
    plan: QueryPlan,
    query: str,
    search_query: str,
    access_context: AccessContext,
    history: list[dict],
    k: int = 3,
) -> HandlerResult:
    """Route to the minimal retrieval path for the given intent."""
    if plan.intent == "clarify_intent":
        return _handle_clarify(query, history)

    if plan.intent == "conversation_meta":
        return _handle_conversation_meta(query, history)

    if plan.strategy in _SCROLL_ONLY_STRATEGIES:
        return _handle_scroll_strategy(plan, query, access_context)

    return _handle_vector_strategy(plan, search_query, access_context, k)


# ── Short-circuit handlers (no note retrieval) ────────────────────────────


def _handle_clarify(query: str, history: list[dict]) -> HandlerResult:
    """Ask a clarifying question — LLM-generated when history exists."""
    if not history:
        return HandlerResult(answer=_CLARIFY_GENERIC)

    t0 = time.monotonic()
    try:
        body = llm_call(
            {
                "model": "llama3.1",
                "messages": [
                    {"role": "system", "content": _CLARIFY_SYSTEM},
                    *history[-6:],
                    {"role": "user", "content": query},
                ],
                "max_tokens": 128,
                "temperature": 0.3,
            },
            timeout=30.0,
        )
        answer = body["choices"][0]["message"]["content"].strip()
        usage = body.get("usage", {})
        return HandlerResult(
            answer=answer,
            inference_ms=int((time.monotonic() - t0) * 1000),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            tokens_used=usage.get("total_tokens", 0),
        )
    except Exception:
        log.warning("handler.clarify_failed", exc_info=True)
        return HandlerResult(answer=_CLARIFY_GENERIC)


def _handle_conversation_meta(query: str, history: list[dict]) -> HandlerResult:
    """Answer a meta-question about the conversation itself."""
    messages: list[dict] = [
        {"role": "system", "content": _CONVERSATION_META_SYSTEM},
    ]
    if history:
        messages.extend(history[-10:])
    messages.append({"role": "user", "content": query})

    t0 = time.monotonic()
    try:
        body = llm_call(
            {"model": "llama3.1", "messages": messages, "max_tokens": 256},
            timeout=60.0,
        )
        answer = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {})
        return HandlerResult(
            answer=answer,
            inference_ms=int((time.monotonic() - t0) * 1000),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            tokens_used=usage.get("total_tokens", 0),
        )
    except Exception:
        log.warning("handler.conversation_meta_failed", exc_info=True)
        return HandlerResult(
            answer="Sorry, I couldn't process that. Could you try again?",
            inference_ms=int((time.monotonic() - t0) * 1000),
        )


# ── Scroll-only handler (chunk scan, no vector search) ───────────────────


def _handle_scroll_strategy(
    plan: QueryPlan,
    query: str,
    access_context: AccessContext,
) -> HandlerResult:
    """Scan all chunks and run the strategy handler — no vector search."""
    t0 = time.monotonic()
    with VectorStore() as db:
        all_chunks = db.scroll_all_chunks(access_context)
    retrieval_ms = int((time.monotonic() - t0) * 1000)

    t1 = time.monotonic()
    result = execute_strategy(plan, all_chunks, query)
    strategy_ms = int((time.monotonic() - t1) * 1000)

    return HandlerResult(
        fact=result.fact,
        source_ids=result.source_ids,
        skip_context=result.skip_context,
        retrieval_ms=retrieval_ms,
        strategy_ms=strategy_ms,
    )


# ── Vector search handler (full RAG pipeline) ────────────────────────────


def _handle_vector_strategy(
    plan: QueryPlan,
    search_query: str,
    access_context: AccessContext,
    k: int,
) -> HandlerResult:
    """Summary search → chunk search → soft score → rerank."""
    t0 = time.monotonic()
    with VectorStore() as db:
        results = db.retrieve_documents(
            search_query, k=k, access_context=access_context,
        )
    retrieval_ms = int((time.monotonic() - t0) * 1000)

    context = "\n\n".join(doc.text for doc in results)
    source_ids = list(dict.fromkeys(
        doc.metadata.get("note_id")
        for doc in results
        if doc.metadata.get("note_id")
    ))

    return HandlerResult(
        context=context,
        source_ids=source_ids,
        retrieval_ms=retrieval_ms,
    )
