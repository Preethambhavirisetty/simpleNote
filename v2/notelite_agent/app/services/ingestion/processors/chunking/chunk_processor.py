from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.core.config import (
    KEYWORD_MIN_CHUNK_TOKENS,
    KEYWORD_OCR_MIN_TOKENS,
    KEYWORD_OCR_SINGLE_CHAR_RATIO,
)
from app.services.ingestion.processors.chunking.chunk_types import ChunkType, classify_chunk_type
from app.services.ingestion.processors.chunking.semantic_chunker import SemanticChunker
from app.services.ingestion.processors.chunking.token_budget import token_count, within_chunk_budget
from app.services.ingestion.processors.chunking.chunk_classifier import split_into_typed_chunks
from app.services.ingestion.processors.text_normalization import repair_ocr_hyphenation


def _split_leading_heading_prefix(text: str) -> tuple[str, str]:
    headings: list[str] = []
    lines = text.splitlines()
    body_start = 0

    for index, line in enumerate(lines):
        clean = line.strip()
        if re.fullmatch(r"#{1,6}\s+\S[^\n]*", clean):
            headings.append(clean)
            body_start = index + 1
            continue
        if headings and not clean:
            body_start = index + 1
            continue
        break

    if not headings:
        return "", text.strip()
    return "\n\n".join(headings), "\n".join(lines[body_start:]).strip()


def _keyword_skip_reason(content: str) -> str:
    count = token_count(content)
    if count < KEYWORD_MIN_CHUNK_TOKENS:
        return "short_chunk"

    lexical_tokens = re.findall(r"\b[\w'-]+\b", content)
    if len(lexical_tokens) < KEYWORD_OCR_MIN_TOKENS:
        return ""
    single_char_ratio = sum(len(token) == 1 for token in lexical_tokens) / len(lexical_tokens)
    if single_char_ratio >= KEYWORD_OCR_SINGLE_CHAR_RATIO:
        return "ocr_single_character_noise"
    return ""


@dataclass(frozen=True)
class TextChunk:
    content: str
    chunk_id: str
    chunk_type: str = ChunkType.CONTENT.value
    metadata: dict[str, Any] = field(default_factory=dict)
    chunk_index: int = 0
    total_chunks: int = 0


class ChunkProcessor:
    """Build typed structural chunks and semantically split substantial prose."""

    def __init__(self):
        self.semantic_chunker = SemanticChunker()
        self.events: list[str] = []

    def process(self, text: str) -> list[TextChunk]:
        """Build final ordered chunks from normalized document text.

        Input:
            A complete document string.

        Output:
            TextChunk(content, chunk_id, chunk_type, chunk_index, total_chunks, metadata),
            where metadata contains available heading context plus has_heading_context,
            token_count, and char_count.
        """
        self.events = [f"chunking started: {token_count(text)} tokens"]
        self.semantic_chunker.events = []
        normalized_text = repair_ocr_hyphenation(text)
        chunks = split_into_typed_chunks(normalized_text)
        self.events.append(f"chunking structural split: {len(chunks)} chunks")

        expanded: list[tuple[str, str]] = []
        semantic_split_count = 0
        for chunk, chunk_type in chunks:
            if chunk_type == ChunkType.CONTENT.value:
                heading_prefix, prose = _split_leading_heading_prefix(chunk)
                parts = self.semantic_chunker.split_prose(prose) if prose else []
                if not parts:
                    expanded.append((chunk, chunk_type))
                    continue
                if heading_prefix:
                    parts[0] = f"{heading_prefix}\n\n{parts[0]}".strip()
                if len(parts) > 1:
                    semantic_split_count += 1
                expanded.extend(
                    (part, classify_chunk_type(part).value)
                    for part in parts
                )
            else:
                expanded.append((chunk, chunk_type))

        self.events.extend(self.semantic_chunker.events)
        if semantic_split_count:
            self.events.append(
                f"chunking semantic split: {semantic_split_count} source chunks; {len(expanded)} total chunks"
            )

        heading_context: dict[int, str] = {}
        output: list[TextChunk] = []
        for index, (chunk, chunk_type) in enumerate(expanded):
            for line in chunk.splitlines():
                match = re.fullmatch(r"(#{1,6})\s+(\S[^\n]*)", line.strip())
                if not match:
                    continue
                depth = len(match.group(1))
                heading_context[depth] = match.group(2).strip()
                for child_depth in [key for key in heading_context if key > depth]:
                    del heading_context[child_depth]

            metadata = {
                f"h{depth}": heading_context[depth]
                for depth in sorted(heading_context)
            }
            if metadata:
                metadata["heading_context"] = " > ".join(metadata[key] for key in sorted(metadata))
            output.append(TextChunk(chunk, str(index), chunk_type, metadata))
        final_chunks = self._merge_compatible_section_chunks(output)
        merged_count = len(output) - len(final_chunks)
        if merged_count:
            self.events.append(f"chunking compatible merges: {merged_count}")
        self.events.append(f"chunking completed: {len(final_chunks)} chunks")
        return final_chunks

    @staticmethod
    def _merge_compatible_section_chunks(chunks: list[TextChunk]) -> list[TextChunk]:
        compatible_groups = (
            {ChunkType.ADDRESS.value, ChunkType.CONTACT.value},
            {ChunkType.QUOTE.value},
            {ChunkType.LIST.value, ChunkType.STRUCTURED_LIST.value},
        )
        appendix_types = {
            ChunkType.APPENDIX.value,
            ChunkType.CONTENT.value,
            ChunkType.LIST.value,
            ChunkType.STRUCTURED_LIST.value,
        }
        merged: list[TextChunk] = []
        for chunk in chunks:
            if merged:
                previous = merged[-1]
                same_section = (
                    previous.metadata.get("heading_context")
                    and previous.metadata.get("heading_context") == chunk.metadata.get("heading_context")
                )
                compatible = any(
                    previous.chunk_type in group and chunk.chunk_type in group
                    for group in compatible_groups
                ) or (
                    ChunkType.APPENDIX.value in {previous.chunk_type, chunk.chunk_type}
                    and previous.chunk_type in appendix_types
                    and chunk.chunk_type in appendix_types
                )
                candidate = f"{previous.content}\n\n{chunk.content}".strip()
                if same_section and compatible and within_chunk_budget(candidate):
                    merged[-1] = TextChunk(
                        content=candidate,
                        chunk_id=previous.chunk_id,
                        chunk_type=classify_chunk_type(candidate).value,
                        metadata=dict(previous.metadata),
                    )
                    continue
            merged.append(chunk)

        total_chunks = len(merged)
        final_chunks = []
        for index, chunk in enumerate(merged):
            skip_keywords_reason = _keyword_skip_reason(chunk.content)
            final_chunks.append(
                TextChunk(
                    content=chunk.content,
                    chunk_id=str(index),
                    chunk_type=chunk.chunk_type,
                    metadata={
                        **chunk.metadata,
                        "has_heading_context": bool(chunk.metadata.get("heading_context")),
                        "token_count": token_count(chunk.content),
                        "char_count": len(chunk.content),
                        "skip_keywords": bool(skip_keywords_reason),
                        "skip_keywords_reason": skip_keywords_reason,
                    },
                    chunk_index=index,
                    total_chunks=total_chunks,
                )
            )
        return final_chunks
