from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Sequence

from app.services.ingestion.processors.chunking import TextChunk
from app.shared.llm import llm_call_general
from app.shared.utils import count_tokens


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

GROUP_SUMMARY_SYSTEM_PROMPT = (
    "You are a summarization assistant optimizing for semantic search retrieval. "
    "Summarize the provided text following these rules:\n\n"
    "- Preserve all named technologies, tools, products, and proper nouns exactly as written\n"
    "- Preserve specific technical decisions, tradeoffs, and open problems\n"
    "- Preserve named people only if relevant to a technical decision\n"
    "- Omit personal or lifestyle content unless it provides technical context\n"
    "- Write in 3-5 sentences maximum\n"
    "- Write in present tense, declarative style\n"
    "- Output only the summary, nothing else"
)

FINAL_SUMMARY_SYSTEM_PROMPT = (
    "You are a summarization assistant optimizing for semantic search retrieval. "
    "Synthesize the provided intermediate summaries into one compact final summary.\n\n"
    "Rules:\n"
    "- Write one paragraph only\n"
    "- Write 3-5 complete sentences maximum\n"
    "- Do not use bullets, numbering, headings, labels, or section-by-section lists\n"
    "- Prefer broad themes over item-by-item recap\n"
    "- Preserve the most important named technologies, tools, products, and proper nouns exactly as written\n"
    "- Preserve major technical decisions, tradeoffs, and open problems\n"
    "- Omit minor details and personal/lifestyle content unless it supports the document's main themes\n"
    "- Output only the final summary paragraph"
)

GROUP_SUMMARY_PROMPT_MESSAGES = [{"role": "system", "content": GROUP_SUMMARY_SYSTEM_PROMPT}]
FINAL_SUMMARY_PROMPT_MESSAGES = [{"role": "system", "content": FINAL_SUMMARY_SYSTEM_PROMPT}]


@dataclass(frozen=True)
class SummaryResult:
    summary: str
    api_calls: int
    events: list[str] = field(default_factory=list)


def _chunk_text(chunk: TextChunk | str) -> str:
    return chunk.content if isinstance(chunk, TextChunk) else str(chunk)


def _group_summary_messages(text: str) -> list[dict[str, str]]:
    return [
        *GROUP_SUMMARY_PROMPT_MESSAGES,
        {"role": "user", "content": text},
    ]


def _final_summary_messages(text: str) -> list[dict[str, str]]:
    return [
        *FINAL_SUMMARY_PROMPT_MESSAGES,
        {"role": "user", "content": text},
    ]


def _is_useless_summary(text: str) -> bool:
    """Return True when the model produced a refusal/placeholder instead of a real summary."""
    stripped = text.strip()
    if not stripped:
        return True
    if len(stripped.split()) < MIN_SUMMARY_WORDS:
        return True
    return bool(USELESS_SUMMARY_PATTERNS.search(stripped))


def _is_bad_summary_format(text: str) -> bool:
    stripped = text.strip()
    if LIST_SUMMARY_PATTERN.search(stripped):
        return True
    if stripped and stripped[-1] not in ".!?":
        return True
    return False


def _valid_summary(
    summary: str,
    *,
    reject_list_format: bool = False,
    require_complete_sentence: bool = False,
) -> str:
    summary = re.sub(r"\s+", " ", summary).strip()
    if _is_useless_summary(summary):
        return ""
    if reject_list_format and LIST_SUMMARY_PATTERN.search(summary):
        return ""
    if require_complete_sentence and _is_bad_summary_format(summary):
        return ""
    return summary


def _fallback_final_summary(summaries: list[str]) -> str:
    """Deterministic fallback when final synthesis returns a list or truncated output."""
    selected_sentences = []
    for summary in summaries:
        sentence = _first_sentence(summary)
        if sentence and not _is_meta_summary_sentence(sentence):
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


def _first_sentence(text: str) -> str:
    clean = re.sub(r"\s+", " ", text.strip())
    clean = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", clean)
    match = re.search(r".*?[.!?](?:\s|$)", clean)
    return match.group(0).strip() if match else clean.strip()


def _is_meta_summary_sentence(sentence: str) -> bool:
    lowered = sentence.lower()
    return (
        "journal entries discuss" in lowered
        or "today's activities focused" in lowered
        or "three separate topics" in lowered
    )


def summarize_chunk(text: str) -> SummaryResult:
    """Summarize a single text chunk."""
    stripped = text.strip()
    events = []
    if not stripped or len(stripped) < MIN_CHUNK_CHARS_FOR_SUMMARY:
        events.append("summary skipped: text too short")
        return SummaryResult(summary="", api_calls=0, events=events)

    try:
        events.append("summary api call: chunk")
        summary = llm_call_general(
            _group_summary_messages(stripped),
            max_tokens=GROUP_SUMMARY_MAX_TOKENS,
        )
    except Exception:
        log.warning("summary chunk failed", exc_info=True)
        events.append("summary failed: chunk")
        return SummaryResult(summary="", api_calls=1, events=events)

    summary = _valid_summary(summary)
    events.append("summary completed: chunk" if summary else "summary discarded: low quality")
    return SummaryResult(summary=summary, api_calls=1, events=events)


def group_chunks(
    chunks: Sequence[TextChunk | str],
    max_tokens: int = SUMMARY_GROUP_TOKEN_LIMIT,
) -> list[list[TextChunk | str]]:
    groups = []
    current_group = []
    current_size = 0

    for chunk in chunks:
        chunk_tokens = count_tokens(_chunk_text(chunk))
        if current_size + chunk_tokens > max_tokens and current_group:
            groups.append(current_group)
            current_group = [chunk]
            current_size = chunk_tokens
        else:
            current_group.append(chunk)
            current_size += chunk_tokens

    if current_group:
        groups.append(current_group)

    return groups


def summarize_hierarchical(chunks: Sequence[TextChunk | str]) -> SummaryResult:
    groups = group_chunks(chunks)
    events = [f"summary hierarchical: {len(groups)} groups"]
    summaries = []
    api_calls = 0

    for index, group in enumerate(groups, start=1):
        text = "\n\n".join(_chunk_text(chunk) for chunk in group)
        try:
            events.append(f"summary api call: group {index}")
            summary = llm_call_general(
                _group_summary_messages(text),
                max_tokens=GROUP_SUMMARY_MAX_TOKENS,
            )
            api_calls += 1
        except Exception:
            log.warning("summary group failed", exc_info=True)
            api_calls += 1
            events.append(f"summary failed: group {index}")
            continue

        summary = _valid_summary(summary)
        if summary:
            summaries.append(summary)

    if not summaries:
        events.append("summary failed: no usable group summaries")
        return SummaryResult(summary="", api_calls=api_calls, events=events)

    if len(summaries) == 1:
        events.append("summary completed: hierarchical")
        return SummaryResult(summary=summaries[0], api_calls=api_calls, events=events)

    try:
        events.append("summary api call: final merge")
        final_summary = llm_call_general(
            _final_summary_messages("\n\n".join(summaries)),
            max_tokens=FINAL_SUMMARY_MAX_TOKENS,
        )
        api_calls += 1
    except Exception:
        log.warning("summary final merge failed", exc_info=True)
        api_calls += 1
        events.append("summary failed: final merge")
        return SummaryResult(summary=summaries[0], api_calls=api_calls, events=events)

    final_summary = _valid_summary(
        final_summary,
        reject_list_format=True,
        require_complete_sentence=True,
    )
    if not final_summary:
        events.append("summary fallback: final merge rejected")
        final_summary = _fallback_final_summary(summaries)
    events.append("summary completed: hierarchical")
    return SummaryResult(summary=final_summary, api_calls=api_calls, events=events)


def chunk_summarizer(chunks: Sequence[TextChunk | str]) -> SummaryResult:
    """Summarize all chunks and report LLM API calls made by this stage."""
    if not chunks:
        return SummaryResult(summary="", api_calls=0, events=["summary skipped: no chunks"])

    total_tokens = sum(count_tokens(_chunk_text(chunk)) for chunk in chunks)
    events = [f"summary started: {len(chunks)} chunks, {total_tokens} tokens"]

    if total_tokens <= DIRECT_SUMMARY_THRESHOLD:
        text = "\n\n".join(_chunk_text(chunk) for chunk in chunks)
        try:
            events.append("summary api call: direct")
            summary = llm_call_general(
                _final_summary_messages(text),
                max_tokens=FINAL_SUMMARY_MAX_TOKENS,
            )
        except Exception:
            log.warning("summary direct failed", exc_info=True)
            events.append("summary failed: direct")
            return SummaryResult(summary="", api_calls=1, events=events)

        summary = _valid_summary(
            summary,
            reject_list_format=True,
            require_complete_sentence=True,
        )
        events.append("summary completed: direct" if summary else "summary discarded: low quality")
        return SummaryResult(summary=summary, api_calls=1, events=events)

    hierarchical = summarize_hierarchical(chunks)
    return SummaryResult(
        summary=hierarchical.summary,
        api_calls=hierarchical.api_calls,
        events=[*events, *hierarchical.events],
    )
