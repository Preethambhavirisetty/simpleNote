from __future__ import annotations

import re

from app.services.ingestion.processors.chunking.patterns import (
    DIVIDER_LINE_PATTERN,
    EMPTY_LIST_ITEM_PATTERN,
    SENTINEL_LINE_PATTERN,
)
from app.services.ingestion.processors.chunking.token_budget import (
    token_count,
    within_chunk_budget,
)
from app.services.ingestion.processors.chunking.validators import (
    has_parent_context,
    heading_number_prefix,
    is_address_like_chunk,
    is_heading_like,
    is_heading_only_chunk,
    is_list_chunk,
    is_signature_like_chunk,
    is_table_like,
    is_table_rowish_chunk,
    validate_chunk,
)
from app.services.ingestion.processors.chunking.window_chunker import WindowChunker


MIN_CHUNK_TOKENS = 25


class ChunkPostProcessor:

    def __init__(self, window_chunker: WindowChunker | None = None):
        self._window_chunker = window_chunker or WindowChunker()

    def process(self, chunks: list[str]) -> list[str]:
        cleaned_chunks = [
            clean
            for chunk in chunks
            if (clean := self._normalize(chunk)) and validate_chunk(clean) == "VALID"
        ]

        merged_chunks = self._merge_orphan_headings(cleaned_chunks)
        linked_chunks = self._link_list_chunks(merged_chunks)
        bounded_chunks = self._enforce_size(linked_chunks)
        sized_chunks = self._merge_short_chunks(bounded_chunks)
        connected_chunks = self._merge_table_and_contact_chunks(sized_chunks)
        processed_chunks = self._drop_heading_only_chunks(connected_chunks)
        return processed_chunks

    def _normalize(self, chunk: str) -> str:
        clean = DIVIDER_LINE_PATTERN.sub("", chunk)
        clean = SENTINEL_LINE_PATTERN.sub("", clean)
        clean = EMPTY_LIST_ITEM_PATTERN.sub("", clean)
        clean = re.sub(r"\n{3,}", "\n\n", clean).strip()

        if clean.count("```") % 2 == 1:
            clean = f"{clean}\n```"

        return clean

    @staticmethod
    def _merge_orphan_headings(chunks: list[str]) -> list[str]:
        merged = []
        index = 0

        while index < len(chunks):
            current = chunks[index]
            if index + 1 < len(chunks):
                nxt = chunks[index + 1]
                candidate = f"{current}\n{nxt}".strip()
                if (
                    ChunkPostProcessor._should_merge_orphan_heading(current, nxt)
                    and within_chunk_budget(candidate)
                ):
                    merged.append(candidate)
                    index += 2
                    continue

            merged.append(current)
            index += 1

        return merged

    @staticmethod
    def _should_merge_orphan_heading(current: str, nxt: str) -> bool:
        if is_heading_like(nxt) or nxt.endswith(":"):
            return False
        return (
            is_heading_like(current)
            or current.endswith(":")
            or validate_chunk(current) == "NEEDS_MERGE"
        )

    @staticmethod
    def _link_list_chunks(chunks: list[str]) -> list[str]:
        linked = []
        for index, chunk in enumerate(chunks):
            next_chunk = chunks[index + 1] if index + 1 < len(chunks) else None
            if linked and ChunkPostProcessor._should_link_list_chunk(
                linked[-1], chunk, next_chunk
            ):
                candidate = f"{linked[-1]}\n{chunk}".strip()
                if within_chunk_budget(candidate):
                    linked[-1] = candidate
                    continue
            linked.append(chunk)

        return linked

    @staticmethod
    def _should_link_list_chunk(
        previous: str,
        current: str,
        next_chunk: str | None,
    ) -> bool:
        if not has_parent_context(previous):
            return False
        if is_list_chunk(current):
            return True
        return (
            ChunkPostProcessor._is_numbered_list_sequence_item(current)
            and next_chunk is not None
            and ChunkPostProcessor._is_numbered_list_sequence_item(next_chunk)
        )

    @staticmethod
    def _is_numbered_list_sequence_item(chunk: str) -> bool:
        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        if len(lines) != 1:
            return False
        first_line = lines[0]
        return bool(re.match(r"^\d+[.)]\s+", first_line)) and ">" not in first_line

    def _enforce_size(self, chunks: list[str]) -> list[str]:
        final_chunks = []
        for chunk in chunks:
            if within_chunk_budget(chunk):
                final_chunks.append(chunk)
            else:
                final_chunks.extend(self._window_chunker.split(chunk))
        return final_chunks

    @staticmethod
    def _extract_heading_prefix(chunk: str) -> str | None:
        return heading_number_prefix(chunk)

    @staticmethod
    def _can_merge_under_same_heading_branch(prev: str, current: str) -> bool:
        prev_prefix = ChunkPostProcessor._extract_heading_prefix(prev)
        current_prefix = ChunkPostProcessor._extract_heading_prefix(current)
        if prev_prefix and current_prefix and prev_prefix != current_prefix:
            return False
        if current_prefix and not prev_prefix:
            return False
        return True

    @staticmethod
    def _merge_short_chunks(chunks: list[str]) -> list[str]:
        merged = []
        for chunk in chunks:
            if token_count(chunk) < MIN_CHUNK_TOKENS and merged:
                if not ChunkPostProcessor._can_merge_under_same_heading_branch(
                    merged[-1], chunk
                ):
                    merged.append(chunk)
                    continue

                candidate = f"{merged[-1]}\n{chunk}".strip()
                if within_chunk_budget(candidate):
                    merged[-1] = candidate
                    continue
            merged.append(chunk)

        return merged

    @staticmethod
    def _merge_table_and_contact_chunks(chunks: list[str]) -> list[str]:
        merged = []
        for chunk in chunks:
            if merged:
                prev = merged[-1]
                candidate = f"{prev}\n{chunk}".strip()
                if (
                    ChunkPostProcessor._should_merge_table_or_contact(prev, chunk)
                    and within_chunk_budget(candidate)
                ):
                    merged[-1] = candidate
                    continue
            merged.append(chunk)

        return merged

    @staticmethod
    def _should_merge_table_or_contact(prev: str, current: str) -> bool:
        table_merge = (
            (is_table_like(prev) and is_table_rowish_chunk(current))
            or (is_table_like(current) and is_table_rowish_chunk(prev))
        )
        contact_merge = ChunkPostProcessor._should_merge_contact_chunk(prev, current)
        return table_merge or contact_merge

    @staticmethod
    def _should_merge_contact_chunk(prev: str, current: str) -> bool:
        if is_heading_only_chunk(prev):
            return False

        previous_is_contact = (
            is_address_like_chunk(prev)
            or is_signature_like_chunk(prev)
            or "contact" in prev.lower()
        )
        current_is_contact = (
            is_address_like_chunk(current)
            or is_signature_like_chunk(current)
            or "best regards" in current.lower()
        )
        if previous_is_contact and ChunkPostProcessor._starts_new_contact_block(current):
            return False
        if previous_is_contact and current_is_contact:
            return True
        if is_address_like_chunk(prev) and not is_heading_only_chunk(current):
            return True
        return is_signature_like_chunk(current) and not is_heading_only_chunk(prev)

    @staticmethod
    def _starts_new_contact_block(chunk: str) -> bool:
        first_line = chunk.splitlines()[0].strip() if chunk.strip() else ""
        return bool(re.search(r"(?:office|headquarters):?\*{0,2}$", first_line, re.IGNORECASE))

    @staticmethod
    def _drop_heading_only_chunks(chunks: list[str]) -> list[str]:
        return [chunk for chunk in chunks if not is_heading_only_chunk(chunk)]
