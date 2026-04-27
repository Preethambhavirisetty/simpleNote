"""Intent-specific retrieval handlers.

call_sql_service():
    intents: list_notes, temporal, keyword_count, presence_check, keyword_count, corpus_stats
    intent specific logic + execute SQL query
        - ex: temporal: extract date/day/time/month/year

call_vector_service():
    intents: semantic, locate_note

if not call_sql_service and not call_vector_service:
    intents: clarify_intent, conversation_meta
    generate clarifying questions and pass it to LLM(for now) / pass history to inference

"""

from pipeline.intent import QueryPlan
from core.contracts import AccessContext
from pipeline.strategies import (
    handle_semantic_intent,
    handle_locate_note_intent,
    handle_list_notes_intent,
    handle_keyword_count_intent,
    handle_temporal_intent,
    handle_presence_check_intent,
    handle_compare_notes_intent,
    handle_corpus_stats_intent,
    handle_conversation_meta_intent,
    handle_clarify_intent,
)

def handle_intent(
    intent: str,
    query: str,
    access_context: AccessContext,
    history: list[dict],
    db,
    qdrant,
    k: int = 3
):

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