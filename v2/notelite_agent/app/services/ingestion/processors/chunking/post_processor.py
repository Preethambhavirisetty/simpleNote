from __future__ import annotations

import re

from app.core.config import MAX_CHUNK_SIZE
from app.services.ingestion.processors.chunking.patterns import (
    DIVIDER_LINE_PATTERN,
    EMPTY_LIST_ITEM_PATTERN,
    SENTINEL_LINE_PATTERN,
)
from app.services.ingestion.processors.chunking.validators import (
    has_parent_context,
    is_address_like_chunk,
    is_heading_like,
    is_list_chunk,
    is_table_like,
    is_table_rowish_chunk,
    validate_chunk,
)
from app.services.ingestion.processors.chunking.window_chunker import WindowChunker


class ChunkPostProcessor:
    """Final cleanup and merge heuristics for chunk quality."""

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

        return self._merge_table_and_address_chunks(bounded_chunks)

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
                should_merge = (
                    is_heading_like(current)
                    or current.endswith(":")
                    or validate_chunk(current) == "NEEDS_MERGE"
                )
                candidate = f"{current}\n{nxt}".strip()
                if should_merge and len(candidate) <= MAX_CHUNK_SIZE:
                    merged.append(candidate)
                    index += 2
                    continue

            merged.append(current)
            index += 1

        return merged

    @staticmethod
    def _link_list_chunks(chunks: list[str]) -> list[str]:
        linked = []
        for chunk in chunks:
            if linked and is_list_chunk(chunk) and has_parent_context(linked[-1]):
                candidate = f"{linked[-1]}\n{chunk}".strip()
                if len(candidate) <= MAX_CHUNK_SIZE:
                    linked[-1] = candidate
                    continue
            linked.append(chunk)

        return linked

    def _enforce_size(self, chunks: list[str]) -> list[str]:
        final_chunks = []
        for chunk in chunks:
            if len(chunk) <= MAX_CHUNK_SIZE:
                final_chunks.append(chunk)
            else:
                final_chunks.extend(self._window_chunker.split(chunk))
        return final_chunks

    @staticmethod
    def _merge_table_and_address_chunks(chunks: list[str]) -> list[str]:
        merged = []
        for chunk in chunks:
            if merged:
                prev = merged[-1]
                table_merge = (
                    (is_table_like(prev) and is_table_rowish_chunk(chunk))
                    or (is_table_like(chunk) and is_table_rowish_chunk(prev))
                )
                address_merge = (
                    (is_address_like_chunk(prev) and not is_heading_like(chunk))
                    or ("contact" in prev.lower() and is_address_like_chunk(chunk))
                )
                candidate = f"{prev}\n{chunk}".strip()
                if (table_merge or address_merge) and len(candidate) <= MAX_CHUNK_SIZE:
                    merged[-1] = candidate
                    continue
            merged.append(chunk)

        return merged
