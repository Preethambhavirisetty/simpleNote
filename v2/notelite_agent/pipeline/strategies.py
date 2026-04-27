"""Strategy executors for query plans.

Each strategy receives retrieved chunks (or all user chunks) and produces
an optional deterministic fact that gets injected into the LLM prompt.
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class HandlerResult:
    response_mode: str
    intent: str
    citations: list[str]
    source_ids: list[str]
    context: str
    used_llm: bool


# all_intents = [semantic, locate_note, list_notes, keyword_count, temporal, presence_check, compare_notes, corpus_stats, conversation_meta, clarify_intent]

# --- PostgreSQL Handlers ----------------------
def handle_list_notes_intent(query):
    """Handle 'list_notes' intent: perform a SQL SELECT for note listings."""
    

def handle_temporal_intent(query):
    """Handle 'temporal' intent: filter/search notes by time range."""
    pass

def handle_presence_check_intent(query):
    """Handle 'presence_check' intent: check for presence/existence of a topic/note."""
    pass

def handle_keyword_count_intent(query):
    """Handle 'keyword_count' intent: count keywords or notes with keyword."""
    pass

def handle_corpus_stats_intent(query):
    """Handle 'corpus_stats' intent: aggregate stats across all notes."""
    pass

# --- Qdrant Handlers ----------------------
def handle_semantic_intent(query, k):
    """Handle 'semantic' intent: likely triggers vector search."""
    pass

def handle_locate_note_intent(query):
    """Handle 'locate_note' intent: hybrid vector+metadata search."""
    pass

def handle_compare_notes_intent(query):
    """Handle 'compare_notes' intent: retrieve and compare two or more notes."""
    pass

# --- LLM-only Handlers ----------------------
def handle_conversation_meta_intent(query):
    """Handle 'conversation_meta' intent: respond about the conversation itself (not notes)."""
    pass

def handle_clarify_intent(query):
    """Handle 'clarify_intent' intent: request clarifying information from user."""
    pass