"""LLM-powered enrichment stages: summarization, keyword dedup, question generation.

Each function is fault-tolerant — returns empty results on failure so the
ingestion pipeline can continue with degraded quality rather than crashing.
All LLM HTTP traffic goes through the single ``llm_call`` in pipeline/llm.py.
"""

import re

import structlog

from core.config import LLM_API_BASE
from pipeline.llm import llm_call

log = structlog.get_logger()

_MISTRAL_TIMEOUT = 120.0
_MISTRAL_MODEL = "mistral-7b"
_MIN_SUMMARY_WORDS = 5
_MIN_CHUNK_CHARS_FOR_SUMMARY = 30
_SUMMARIZATION_CHAR_CAP = 2000
_MAX_RECURSION_DEPTH = 5

_USELESS_SUMMARY_PATTERNS = re.compile(
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


def _is_useless_summary(text: str) -> bool:
    """Return True when the model produced a refusal/placeholder instead of a real summary."""
    stripped = text.strip()
    if not stripped:
        return True
    if len(stripped.split()) < _MIN_SUMMARY_WORDS:
        return True
    if _USELESS_SUMMARY_PATTERNS.search(stripped):
        return True
    return False


def summarize_chunk(text: str) -> str:
    """Summarize a chunk into 1-2 sentences. Returns empty string on failure."""
    stripped = text.strip()
    if not stripped or len(stripped) < _MIN_CHUNK_CHARS_FOR_SUMMARY:
        return ""

    try:
        body = llm_call(
            {
                "model": _MISTRAL_MODEL,
                "messages": [
                    {"role": "system", "content": (
                        "You are a summarization assistant. "
                        "Write 1-2 sentences that capture the main idea of the text. "
                        "If the text is a heading, label, or single phrase with no body, "
                        "describe what kind of content it introduces. "
                        "Never say 'no text provided' or 'no summary to provide' — "
                        "always produce a real sentence about the content. "
                        "Output only the summary — nothing else."
                    )},
                    {"role": "user", "content": text},
                ],
                "max_tokens": 80,
                "temperature": 0.1,
            },
            base_url=LLM_API_BASE,
            timeout=_MISTRAL_TIMEOUT,
            params={"purpose": "summarization"},
        )
        result = body["choices"][0]["message"]["content"].strip()
    except Exception:
        log.warning("enrichment.summarize_failed", input_chars=len(text), exc_info=True)
        return ""

    if _is_useless_summary(result):
        return ""
    return result


def merge_for_summarization(texts: list[str], char_cap: int = _SUMMARIZATION_CHAR_CAP) -> list[str]:
    """Merge adjacent small texts into groups up to char_cap for efficient LLM summarization."""
    groups: list[str] = []
    current_parts: list[str] = []
    current_len = 0
    for text in texts:
        text_len = len(text)
        if current_parts and current_len + text_len > char_cap:
            groups.append("\n\n".join(current_parts))
            current_parts = [text]
            current_len = text_len
        else:
            current_parts.append(text)
            current_len += text_len
    if current_parts:
        groups.append("\n\n".join(current_parts))
    return groups


def recursive_summarize(chunks: list[str], _depth: int = 0) -> str:
    """Recursively merge and summarize until a single overall summary is produced."""
    if not chunks:
        return ""
    if len(chunks) == 1:
        return summarize_chunk(chunks[0]) or chunks[0][:200]
    if _depth >= _MAX_RECURSION_DEPTH:
        combined = " ".join(chunks)
        return summarize_chunk(combined) or combined[:200]

    groups = merge_for_summarization(chunks)
    summaries = []
    for group in groups:
        summary = summarize_chunk(group)
        summaries.append(summary if summary else group[:200])

    return recursive_summarize(summaries, _depth + 1)


def deduplicate_keywords_llm(keywords: list[str]) -> list[str]:
    """Use LLM to deduplicate keywords into top 15 unique, high-signal themes."""
    if not keywords:
        return []

    keyword_text = ", ".join(keywords)
    try:
        body = llm_call(
            {
                "model": _MISTRAL_MODEL,
                "messages": [
                    {"role": "system", "content": (
                        "You are a keyword analysis assistant. "
                        "Given a list of keywords from a document, deduplicate them "
                        "and identify the top 15 unique, high-signal themes. "
                        "Return only the themes, one per line. No numbering, no explanations."
                    )},
                    {"role": "user", "content": keyword_text},
                ],
                "max_tokens": 150,
                "temperature": 0.1,
            },
            base_url=LLM_API_BASE,
            timeout=_MISTRAL_TIMEOUT,
            params={"purpose": "dedup"},
        )
        result = body["choices"][0]["message"]["content"].strip()
        return [line.strip() for line in result.splitlines() if line.strip()][:15]
    except Exception:
        log.warning("enrichment.dedup_failed", exc_info=True)

    seen = set()
    deduped = []
    for kw in keywords:
        lower = kw.lower()
        if lower not in seen:
            seen.add(lower)
            deduped.append(kw)
    return deduped[:15]


def generate_questions(overall_summary: str) -> list[str]:
    """Generate 5 diverse questions from the overall summary for the questions vector."""
    if not overall_summary:
        return []

    try:
        body = llm_call(
            {
                "model": _MISTRAL_MODEL,
                "messages": [
                    {"role": "system", "content": (
                        "You are a question generation assistant. "
                        "Given a summary, generate exactly 5 questions a user might ask:\n"
                        "  1 factual question (specific detail)\n"
                        "  1 conceptual question (what/why/how)\n"
                        "  1 summary question (overall/general)\n"
                        "  1 keyword-style query (short, search-like)\n"
                        "  1 follow-up style question (assumes prior context)\n"
                        "Return only the questions, one per line. No numbering or bullets."
                    )},
                    {"role": "user", "content": overall_summary},
                ],
                "max_tokens": 300,
                "temperature": 0.3,
            },
            base_url=LLM_API_BASE,
            timeout=_MISTRAL_TIMEOUT,
            params={"purpose": "questions"},
        )
        result = body["choices"][0]["message"]["content"].strip()
    except Exception:
        log.warning("enrichment.questions_failed", exc_info=True)
        return []

    return [
        line.strip() for line in result.splitlines()
        if line.strip() and line.strip().endswith("?")
    ][:5]
