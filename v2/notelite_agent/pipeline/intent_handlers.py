"""Dispatch intent label to strategy handlers (retrieval only — no chat LLM)."""

from __future__ import annotations

from core.contracts import AccessContext
from pipeline.strategies import (
    HandlerResult,
    handle_clarify_intent,
    handle_compare_notes_intent,
    handle_conversation_meta_intent,
    handle_corpus_stats_intent,
    handle_keyword_count_intent,
    handle_list_notes_intent,
    handle_locate_note_intent,
    handle_presence_check_intent,
    handle_semantic_intent,
    handle_temporal_intent,
)


def handle_intent(
    intent: str,
    query: str,
    access_context: AccessContext,
    history: list[dict],
    k: int = 3,
) -> HandlerResult:
    match intent:
        case "semantic":
            return handle_semantic_intent(access_context, query, k)
        case "locate_note":
            return handle_locate_note_intent(access_context, query, k)
        case "list_notes":
            return handle_list_notes_intent(access_context, query, k)
        case "keyword_count":
            return handle_keyword_count_intent(access_context, query, k)
        case "temporal":
            return handle_temporal_intent(access_context, query, k)
        case "presence_check":
            return handle_presence_check_intent(access_context, query, k)
        case "compare_notes":
            return handle_compare_notes_intent(access_context, query, k)
        case "corpus_stats":
            return handle_corpus_stats_intent(access_context, query, k)
        case "conversation_meta":
            return handle_conversation_meta_intent(access_context, query, history, k)
        case "clarify_intent":
            return handle_clarify_intent(access_context, query, history, k)
        case _:
            return handle_clarify_intent(access_context, query, history, k)
