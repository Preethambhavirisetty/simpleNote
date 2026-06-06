from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.services.ingestion.processors.chunking.chunk_types import ChunkType, classify_chunk_type
from app.services.ingestion.processors.chunking.heading_chunker import HeadingChunker
from app.services.ingestion.processors.chunking.heading_processor import HeadingProcessor
from app.services.ingestion.processors.chunking.post_processor import ChunkPostProcessor
from app.services.ingestion.processors.chunking.semantic_chunker import SemanticChunker
from app.services.ingestion.processors.chunking.token_budget import token_count
from app.services.ingestion.processors.chunking.validators import validate_chunk
from app.services.ingestion.processors.text_normalization import repair_ocr_hyphenation

from app.services.ingestion.processors.chunking.chunk_classifier import split_into_typed_chunks

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TextChunk:
    content: str
    chunk_id: str
    chunk_type: str = ChunkType.CONTENT.value
    metadata: dict[str, Any] = field(default_factory=dict)


class ChunkProcessor:
    """Orchestrates paragraph, heading, semantic, and postprocessing chunk stages."""

    def __init__(self):
        self.heading_chunker = HeadingChunker()
        self.semantic_chunker = SemanticChunker()
        self.heading_processor = HeadingProcessor(self.semantic_chunker)
        self.post_processor = ChunkPostProcessor()

    def split(self, text: str) -> list[str]:
        log.info("Chunking began...")

        normalized_text = repair_ocr_hyphenation(text)
        prepared_text = self.heading_chunker.inject_numbered_line_breaks(normalized_text)
        paragraphs = self._split_paragraphs_preserving_code(prepared_text)

        chunks = []
        pending_paragraph = ""

        heading_context: list[str] = []
        for paragraph in paragraphs:
            current = f"{pending_paragraph}\n{paragraph}".strip() if pending_paragraph else paragraph
            pending_paragraph = ""

            heading_parts = self.heading_chunker.split(current)
            pending_paragraph = self.heading_processor.process(
                heading_parts,
                chunks,
                pending_paragraph,
                heading_context,
            )

        if pending_paragraph and validate_chunk(pending_paragraph) != "DISCARD":
            chunks.append(pending_paragraph)

        final_chunks = self._split_numbered_sections(self.post_processor.process(chunks))
        log.info(
            "Generated %d chunks (original=%d tokens, chunked=%d tokens)",
            len(final_chunks),
            token_count(prepared_text),
            sum(token_count(chunk) for chunk in final_chunks),
        )
        return final_chunks

    def process(self, text: str) -> list[TextChunk]:
        # chunks = self.split(text)
        normalized_text = repair_ocr_hyphenation(text)
        chunks = split_into_typed_chunks(normalized_text)
        # if not chunks and text.strip():
        #     fallback_type = classify_chunk_type(text).value
        #     if fallback_type == ChunkType.HEADING_ONLY.value:
        #         return [TextChunk(content=text.strip(), chunk_id="0", chunk_type=fallback_type)]

        expanded: list[tuple[str, str]] = []
        for chunk, chunk_type in chunks:
            if chunk_type == ChunkType.CONTENT.value:
                expanded.extend(
                    (part, classify_chunk_type(part).value)
                    for part in self.semantic_chunker.split_prose(chunk)
                )
            else:
                expanded.append((chunk, chunk_type))

        heading_context: dict[int, str] = {}
        output: list[TextChunk] = []
        for index, (chunk, chunk_type) in enumerate(expanded):
            for line in chunk.splitlines():
                match = re.match(r"^(#{1,6})\s+(\S.*)$", line.strip())
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
        return output

    @staticmethod
    def _split_numbered_sections(chunks: list[str]) -> list[str]:
        """Keep numbered section lines separate without splitting list runs."""
        output: list[str] = []
        numbered = re.compile(r"^\s*(?P<number>\d+(?:\.\d+)*\.?)\s+\S")

        for chunk in chunks:
            lines = chunk.splitlines()
            groups: list[list[str]] = []
            current: list[str] = []
            for index, line in enumerate(lines):
                match = numbered.match(line)
                next_line = lines[index + 1].strip() if index + 1 < len(lines) else ""
                next_is_numbered = bool(numbered.match(next_line))
                raw_prefix = match.group("number") if match else ""
                prefix = raw_prefix.rstrip(".")
                is_nested_heading = bool(prefix and "." in prefix)
                has_section_marker = is_nested_heading or raw_prefix.endswith(".")
                starts_section = bool(match and has_section_marker and not next_is_numbered)
                if starts_section and current:
                    groups.append(current)
                    current = []
                current.append(line)
            if current:
                groups.append(current)
            output.extend("\n".join(group).strip() for group in groups if "\n".join(group).strip())
        return output

    @staticmethod
    def _split_paragraphs_preserving_code(text: str) -> list[str]:
        paragraphs = []
        current = []
        in_code = False

        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("```"):
                in_code = not in_code
                current.append(line)
                continue

            if not stripped and not in_code:
                paragraph = "\n".join(current).strip()
                if paragraph:
                    paragraphs.append(paragraph)
                current = []
                continue

            current.append(line)

        paragraph = "\n".join(current).strip()
        if paragraph:
            paragraphs.append(paragraph)

        return paragraphs
