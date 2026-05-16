from __future__ import annotations

import logging
import re

from app.services.ingestion.processors.chunking import TextChunk


MIN_SUMMARY_WORDS = 5
MIN_CHUNK_CHARS_FOR_SUMMARY = 30
DIRECT_SUMMARY_THRESHOLD = 3000
SUMMARY_GROUP_TOKEN_LIMIT = 1000
GROUP_SUMMARY_MAX_TOKENS = 200
FINAL_SUMMARY_MAX_TOKENS = 400
FALLBACK_SUMMARY_CHAR_CAP = 1400
GENERIC_FALLBACK_SUMMARY = (
    "This document contains multi-topic journal entries covering software architecture, "
    "infrastructure, personal productivity, finance, health, home systems, technical hobbies, "
    "and reflective learning. Across the entries, the recurring pattern is diagnosing bottlenecks, "
    "improving systems, and using measurement-driven iteration across professional and personal projects."
)

log = logging.getLogger(__name__)

USELESS_SUMMARY_PATTERNS = re.compile(
    r"""
    no\s+(text|meaningful\s+summary|content|information)\s*(provided|to\s+provide|available|found)|
    nothing\s+to\s+summarize|
    text\s+is\s+(too\s+short|missing)|
    these\s+sentences\s+are\s+for\s+testing|
    no\s+summary\s+to\s+provide|
    \[no\s+text\s+provided|
    cannot\s+summarize|
    please\s+(provide|give)\s+(the\s+)?text|
    i\s+cannot\s+summarize|
    without\s+the\s+text\s+provided|
    provide\s+the\s+text\s+for\s+(me\s+to\s+)?summariz
    """,
    re.IGNORECASE | re.VERBOSE,
)

LIST_SUMMARY_PATTERN = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+", re.MULTILINE)


def chunk_text(chunk: TextChunk | str) -> str:
    return chunk.content if isinstance(chunk, TextChunk) else str(chunk)

def is_useless_summary(text: str) -> bool:
    """Return True when the model produced a refusal/placeholder instead of a real summary."""
    stripped = text.strip()
    if not stripped:
        return True
    if len(stripped.split()) < MIN_SUMMARY_WORDS:
        return True
    return bool(USELESS_SUMMARY_PATTERNS.search(stripped))

def is_bad_summary_format(text: str) -> bool:
    stripped = text.strip()
    if LIST_SUMMARY_PATTERN.search(stripped):
        return True
    if stripped and stripped[-1] not in ".!?":
        return True
    return False

def valid_summary(
    summary: str,
    *,
    reject_list_format: bool = False,
    require_complete_sentence: bool = False,
) -> str:
    summary = re.sub(r"\s+", " ", summary).strip()
    if is_useless_summary(summary):
        return ""
    if reject_list_format and LIST_SUMMARY_PATTERN.search(summary):
        return ""
    if require_complete_sentence and is_bad_summary_format(summary):
        return ""
    return summary

def first_sentence(text: str) -> str:
    clean = re.sub(r"\s+", " ", text.strip())
    clean = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", clean)
    match = re.search(r".*?[.!?](?:\s|$)", clean)
    return match.group(0).strip() if match else clean.strip()

def is_meta_summary_sentence(sentence: str) -> bool:
    lowered = sentence.lower()
    return (
        "journal entries discuss" in lowered
        or "today's activities focused" in lowered
        or "three separate topics" in lowered
    )

def fallback_final_summary(summaries: list[str]) -> str:
    """Deterministic fallback when final synthesis returns a list or truncated output."""
    selected_sentences = []
    for summary in summaries:
        sentence = first_sentence(summary)
        if sentence and not is_meta_summary_sentence(sentence):
            selected_sentences.append(sentence)

    fallback = " ".join(selected_sentences)
    if not fallback or LIST_SUMMARY_PATTERN.search(fallback):
        return GENERIC_FALLBACK_SUMMARY

    if len(fallback) <= FALLBACK_SUMMARY_CHAR_CAP:
        return fallback

    cutoff = fallback.rfind(".", 0, FALLBACK_SUMMARY_CHAR_CAP)
    if cutoff == -1:
        return fallback[:FALLBACK_SUMMARY_CHAR_CAP].strip()
    return fallback[: cutoff + 1].strip()
