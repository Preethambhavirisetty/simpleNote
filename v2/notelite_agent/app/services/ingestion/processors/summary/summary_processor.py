from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Sequence

from app.services.ingestion.processors.chunking import TextChunk
from app.services.ingestion.processors.summary.summary_helpers import (
    DIRECT_SUMMARY_THRESHOLD,
    FINAL_SUMMARY_MAX_TOKENS,
    GROUP_SUMMARY_MAX_TOKENS,
    MIN_CHUNK_CHARS_FOR_SUMMARY,
    SUMMARY_GROUP_TOKEN_LIMIT,
    chunk_text,
    fallback_final_summary,
    valid_summary,
)
from app.shared.llm import llm_call_general
from app.shared.utils import count_tokens, build_llm_messages


log = logging.getLogger(__name__)

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

@dataclass(frozen=True)
class SummaryResult:
    summary: str
    api_calls: int
    events: list[str] = field(default_factory=list)


class SummaryProcessor:
    def __init__(self):
        self.api_calls = 0
        self.events: list[str] = []

    def process(self, chunks: Sequence[TextChunk | str]) -> SummaryResult:
        if not chunks:
            return SummaryResult(summary="", api_calls=0, events=["summary skipped: no chunks"])
        
        # count total tokens with tiktoken
        total_tokens = sum(count_tokens(chunk_text(chunk)) for chunk in chunks)
        events = [f"summary started: {len(chunks)} chunks, {total_tokens} tokens"]

        # if total tokens less than configured direct summary tokens
        if total_tokens <= DIRECT_SUMMARY_THRESHOLD:
            # combine all chunk text
            text = "\n\n".join(chunk_text(chunk) for chunk in chunks)
            try:
                events.append("summary api call: direct")
                summary = llm_call_general(
                    build_llm_messages(FINAL_SUMMARY_SYSTEM_PROMPT, text),
                    max_tokens=FINAL_SUMMARY_MAX_TOKENS,
                )
            except Exception:
                log.warning("summary direct failed", exc_info=True)
                events.append("summary failed: direct")
                return SummaryResult(summary="", api_calls=1, events=events)

            summary = valid_summary(
                summary,
                reject_list_format=True,
                require_complete_sentence=True,
            )
            events.append("summary completed: direct" if summary else "summary discarded: low quality")
            return SummaryResult(summary=summary, api_calls=1, events=events)

        # If total tokens exceed direct summary tokens, then compute hierarchial summary
        hierarchical = self.summarize_hierarchical(chunks)
        return SummaryResult(
            summary=hierarchical.summary,
            api_calls=hierarchical.api_calls,
            events=[*events, *hierarchical.events],
        )

    def summarize_hierarchical(self, chunks: Sequence[TextChunk | str]) -> SummaryResult:
        groups = self.group_chunks(chunks)
        events = [f"summary hierarchical: {len(groups)} groups"]
        summaries = []
        api_calls = 0

        for index, group in enumerate(groups, start=1):
            text = "\n\n".join(chunk_text(chunk) for chunk in group)
            try:
                events.append(f"summary api call: group {index}")
                summary = llm_call_general(
                    build_llm_messages(GROUP_SUMMARY_SYSTEM_PROMPT, text),
                    max_tokens=GROUP_SUMMARY_MAX_TOKENS,
                )
                api_calls += 1
            except Exception:
                log.warning("summary group failed", exc_info=True)
                api_calls += 1
                events.append(f"summary failed: group {index}")
                continue

            summary = valid_summary(summary)
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
            llm_text = "\n\n".join(summaries)
            final_summary = llm_call_general(
                build_llm_messages(FINAL_SUMMARY_SYSTEM_PROMPT, llm_text),
                max_tokens=FINAL_SUMMARY_MAX_TOKENS,
            )
            api_calls += 1
        except Exception:
            log.warning("summary final merge failed", exc_info=True)
            api_calls += 1
            events.append("summary failed: final merge")
            return SummaryResult(summary=summaries[0], api_calls=api_calls, events=events)

        final_summary = valid_summary(
            final_summary,
            reject_list_format=True,
            require_complete_sentence=True,
        )
        if not final_summary:
            events.append("summary fallback: final merge rejected")
            final_summary = fallback_final_summary(summaries)
        events.append("summary completed: hierarchical")
        return SummaryResult(summary=final_summary, api_calls=api_calls, events=events)

    def summarize_chunk(self, text: str) -> SummaryResult:
        """Summarize a single text chunk."""
        stripped = text.strip()
        events = []
        if not stripped or len(stripped) < MIN_CHUNK_CHARS_FOR_SUMMARY:
            events.append("summary skipped: text too short")
            return SummaryResult(summary="", api_calls=0, events=events)

        try:
            events.append("summary api call: chunk")
            summary = llm_call_general(
                build_llm_messages(GROUP_SUMMARY_SYSTEM_PROMPT, stripped),
                max_tokens=GROUP_SUMMARY_MAX_TOKENS,
            )
        except Exception:
            log.warning("summary chunk failed", exc_info=True)
            events.append("summary failed: chunk")
            return SummaryResult(summary="", api_calls=1, events=events)

        summary = valid_summary(summary)
        events.append("summary completed: chunk" if summary else "summary discarded: low quality")
        return SummaryResult(summary=summary, api_calls=1, events=events)

    def group_chunks(
        self,
        chunks: Sequence[TextChunk | str],
        max_tokens: int = SUMMARY_GROUP_TOKEN_LIMIT,
    ) -> list[list[TextChunk | str]]:
        groups = []
        current_group = []
        current_size = 0

        for chunk in chunks:
            chunk_tokens = count_tokens(chunk_text(chunk))
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
