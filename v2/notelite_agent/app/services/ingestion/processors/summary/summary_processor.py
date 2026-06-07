from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Sequence

from app.shared.prompts.prompt import get_final_summary_system_prompt, get_group_summary_system_prompt
from app.services.ingestion.processors.chunking import TextChunk
from app.services.ingestion.processors.chunking.chunk_types import ChunkType
from app.services.ingestion.processors.summary.summary_helpers import (
    DIRECT_SUMMARY_THRESHOLD,
    FINAL_SUMMARY_MAX_TOKENS,
    GROUP_SUMMARY_MAX_TOKENS,
    MIN_CHUNK_CHARS_FOR_SUMMARY,
    SUMMARY_GROUP_TOKEN_LIMIT,
    chunk_text,
    estimate_summary_request_tokens,
    fallback_final_summary,
    summary_request_token_limit,
    valid_summary,
)
from app.shared.llm import llm_call_general
from app.shared.utils import count_tokens, build_llm_messages


log = logging.getLogger(__name__)

SUMMARY_SKIP_TYPES = {
    ChunkType.HEADING_ONLY.value,
    ChunkType.CODE.value,
    ChunkType.JSON.value,
    ChunkType.ADDRESS.value,
    ChunkType.CONTACT.value,
    ChunkType.GLOSSARY.value,
    ChunkType.APPENDIX.value,
    # ChunkType.HEADER.value,
    ChunkType.QUOTE.value,
    # ChunkType.OCR_NOISE.value,
    # ChunkType.BOILERPLATE.value,
}

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

        summary_chunks = self._summary_chunks(chunks)
        skipped_count = len(chunks) - len(summary_chunks)
        if not summary_chunks:
            return SummaryResult(
                summary="",
                api_calls=0,
                events=[f"summary skipped: all {len(chunks)} chunks are structural"],
            )

        # count total tokens with tiktoken
        total_tokens = sum(count_tokens(chunk_text(chunk)) for chunk in summary_chunks)
        events = [f"summary started: {len(summary_chunks)} chunks, {total_tokens} tokens"]
        if skipped_count:
            events.append(f"summary skipped structural chunks: {skipped_count}")

        text = "\n\n".join(chunk_text(chunk) for chunk in summary_chunks)
        final_prompt = get_final_summary_system_prompt()
        direct_prompt_tokens = estimate_summary_request_tokens(final_prompt, text)
        direct_prompt_limit = summary_request_token_limit(
            SUMMARY_GROUP_TOKEN_LIMIT, FINAL_SUMMARY_MAX_TOKENS
        )

        # Use a direct call only when both the document and estimated request fit safely.
        if total_tokens <= DIRECT_SUMMARY_THRESHOLD and direct_prompt_tokens <= direct_prompt_limit:
            try:
                events.append(f"summary api call: direct, estimated prompt tokens: {direct_prompt_tokens}")
                summary = llm_call_general(
                    build_llm_messages(final_prompt, text),
                    max_tokens=FINAL_SUMMARY_MAX_TOKENS,
                )
            except Exception as exc:
                log.warning("summary direct failed", exc_info=True)
                events.append(f"summary failed: direct ({self._failure_label(exc)})")
                return SummaryResult(summary="", api_calls=1, events=events)

            summary = valid_summary(
                summary,
                reject_list_format=True,
                require_complete_sentence=True,
            )
            events.append("summary completed: direct" if summary else "summary discarded: low quality")
            return SummaryResult(summary=summary, api_calls=1, events=events)

        # If total tokens exceed direct summary tokens, then compute hierarchial summary
        hierarchical = self.summarize_hierarchical(summary_chunks)
        return SummaryResult(
            summary=hierarchical.summary,
            api_calls=hierarchical.api_calls,
            events=[*events, *hierarchical.events],
        )

    def summarize_hierarchical(self, chunks: Sequence[TextChunk | str]) -> SummaryResult:
        try:
            groups = self.group_chunks(chunks)
        except ValueError as exc:
            log.warning("summary grouping failed: %s", exc)
            return SummaryResult(summary="", api_calls=0, events=[f"summary failed: {exc}"])
        events = [f"summary hierarchical: {len(groups)} groups"]
        summaries = []
        api_calls = 0

        group_prompt = get_group_summary_system_prompt()
        for index, group in enumerate(groups, start=1):
            text = "\n\n".join(chunk_text(chunk) for chunk in group)
            prompt_tokens = estimate_summary_request_tokens(group_prompt, text)
            try:
                events.append(f"summary api call: group {index}, estimated prompt tokens: {prompt_tokens}")
                summary = llm_call_general(
                    build_llm_messages(group_prompt, text),
                    max_tokens=GROUP_SUMMARY_MAX_TOKENS,
                )
                api_calls += 1
                if summary.strip() == "SKIP":
                    events.append(f"summary skipped: group {index}")
                    continue
            except Exception as exc:
                log.warning("summary group failed", exc_info=True)
                api_calls += 1
                events.append(f"summary failed: group {index} ({self._failure_label(exc)})")
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

        llm_text = "\n\n".join(summaries)
        final_prompt = get_final_summary_system_prompt()
        prompt_tokens = estimate_summary_request_tokens(final_prompt, llm_text)
        prompt_limit = summary_request_token_limit(SUMMARY_GROUP_TOKEN_LIMIT, FINAL_SUMMARY_MAX_TOKENS)
        if prompt_tokens > prompt_limit:
            events.append(f"summary fallback: final merge exceeds safe prompt limit ({prompt_tokens} tokens)")
            return SummaryResult(summary=fallback_final_summary(summaries), api_calls=api_calls, events=events)

        try:
            events.append(f"summary api call: final merge, estimated prompt tokens: {prompt_tokens}")
            final_summary = llm_call_general(
                build_llm_messages(final_prompt, llm_text),
                max_tokens=FINAL_SUMMARY_MAX_TOKENS,
            )
            api_calls += 1
        except Exception as exc:
            log.warning("summary final merge failed", exc_info=True)
            api_calls += 1
            events.append(f"summary failed: final merge ({self._failure_label(exc)})")
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

        group_prompt = get_group_summary_system_prompt()
        prompt_tokens = estimate_summary_request_tokens(group_prompt, stripped)
        prompt_limit = summary_request_token_limit(SUMMARY_GROUP_TOKEN_LIMIT, GROUP_SUMMARY_MAX_TOKENS)
        if prompt_tokens > prompt_limit:
            events.append(f"summary failed: chunk exceeds safe prompt limit ({prompt_tokens} tokens)")
            return SummaryResult(summary="", api_calls=0, events=events)

        try:
            events.append(f"summary api call: chunk, estimated prompt tokens: {prompt_tokens}")
            summary = llm_call_general(
                build_llm_messages(group_prompt, stripped),
                max_tokens=GROUP_SUMMARY_MAX_TOKENS,
            )
        except Exception as exc:
            log.warning("summary chunk failed", exc_info=True)
            events.append(f"summary failed: chunk ({self._failure_label(exc)})")
            return SummaryResult(summary="", api_calls=1, events=events)

        if summary.strip() == "SKIP":
            events.append("summary skipped: chunk")
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
        system_prompt = get_group_summary_system_prompt()
        prompt_limit = summary_request_token_limit(max_tokens, GROUP_SUMMARY_MAX_TOKENS)
        if prompt_limit <= 0:
            raise ValueError("summary context window leaves no prompt budget")

        for chunk in chunks:
            candidate = [*current_group, chunk]
            candidate_text = "\n\n".join(chunk_text(item) for item in candidate)
            candidate_tokens = estimate_summary_request_tokens(system_prompt, candidate_text)
            if candidate_tokens > prompt_limit and current_group:
                groups.append(current_group)
                current_group = [chunk]
                single_tokens = estimate_summary_request_tokens(system_prompt, chunk_text(chunk))
                if single_tokens > prompt_limit:
                    raise ValueError(f"summary chunk exceeds safe prompt limit ({single_tokens} tokens)")
            elif candidate_tokens > prompt_limit:
                raise ValueError(f"summary chunk exceeds safe prompt limit ({candidate_tokens} tokens)")
            else:
                current_group.append(chunk)

        if current_group:
            groups.append(current_group)

        return groups

    @staticmethod
    def _summary_chunks(chunks: Sequence[TextChunk | str]) -> list[TextChunk | str]:
        return [
            chunk
            for chunk in chunks
            if not isinstance(chunk, TextChunk) or chunk.chunk_type not in SUMMARY_SKIP_TYPES
        ]

    @staticmethod
    def _failure_label(exc: Exception) -> str:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        return f"{type(exc).__name__} status={status_code}" if status_code else type(exc).__name__


if __name__ == "__main__":
    text = """Hush, hush! for pity's sake! I must not listen to such words from a
stranger. I am ungrateful to call you a stranger. Oh! how one may be
mistaken! If I had known you were so bold--” And Margaret's bosom began
to heave, and her cheeks were covered with blushes, and she looked
towards her sleeping father, very much like a timid thing that meditates
actual flight.

Then Gerard was frightened at the alarm he caused. “Forgive me,” said he
imploringly. “How could any one help loving you?”

“Well, sir, I will try and forgive you--you are so good in other
respects; but then you must promise me never to say you--to say that
again.”

“Give me your hand then, or you don't forgive me.”

She hesitated; but eventually put out her hand a very little way, very
slowly, and with seeming reluctance. He took it, and held it prisoner.
When she thought it had been there long enough, she tried gently to draw
it away. He held it tight: it submitted quite patiently to force.
What is the use resisting force. She turned her head away, and her long
eyelashes drooped sweetly. Gerard lost nothing by his promise. Words
were not needed here; and silence was more eloquent. Nature was in that
day what she is in ours; but manners were somewhat freer. Then as now,
virgins drew back alarmed at the first words of love; but of prudery
and artificial coquetry there was little, and the young soon read one
another's hearts. Everything was on Gerard's side, his good looks, her
belief in his goodness, her gratitude; and opportunity for at the Duke's
banquet this mellow summer eve, all things disposed the female nature
to tenderness: the avenues to the heart lay open; the senses were so
soothed and subdued with lovely colours, gentle sounds, and delicate
odours; the sun gently sinking, the warm air, the green canopy, the cool
music of the now violet fountain.
"""
    sp = SummaryProcessor()
    res = sp.summarize_chunk(text)
    print(res)