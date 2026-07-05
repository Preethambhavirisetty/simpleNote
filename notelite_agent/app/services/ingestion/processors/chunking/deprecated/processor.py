from __future__ import annotations

import logging
import re

from app.services.ingestion.processors.chunking.deprecated.heading_chunker import HeadingChunker
from app.services.ingestion.processors.chunking.deprecated.heading_processor import HeadingProcessor
from app.services.ingestion.processors.chunking.deprecated.post_processor import ChunkPostProcessor
from app.services.ingestion.processors.chunking.semantic_chunker import SemanticChunker
from app.services.ingestion.processors.chunking.token_budget import token_count
from app.services.ingestion.processors.chunking.validators import validate_chunk
from app.services.ingestion.processors.text_normalization import repair_ocr_hyphenation

log = logging.getLogger(__name__)


class DeprecatedChunkProcessor:
    """Deprecated heading-oriented chunking pipeline."""

    def __init__(self):
        self.heading_chunker = HeadingChunker()
        self.semantic_chunker = SemanticChunker()
        self.heading_processor = HeadingProcessor(self.semantic_chunker)
        self.post_processor = ChunkPostProcessor()

    def split(self, text: str) -> list[str]:
        normalized_text = repair_ocr_hyphenation(text)
        prepared_text = self.heading_chunker.inject_numbered_line_breaks(normalized_text)
        paragraphs = self._split_paragraphs_preserving_code(prepared_text)

        chunks: list[str] = []
        pending_paragraph = ""
        heading_context: list[str] = []
        for paragraph in paragraphs:
            current = f"{pending_paragraph}\n{paragraph}".strip() if pending_paragraph else paragraph
            pending_paragraph = self.heading_processor.process(
                self.heading_chunker.split(current),
                chunks,
                "",
                heading_context,
            )

        if pending_paragraph and validate_chunk(pending_paragraph) != "DISCARD":
            chunks.append(pending_paragraph)

        final_chunks = self._split_numbered_sections(self.post_processor.process(chunks))
        log.info(
            "Generated %d deprecated chunks (original=%d tokens, chunked=%d tokens)",
            len(final_chunks),
            token_count(prepared_text),
            sum(token_count(chunk) for chunk in final_chunks),
        )
        return final_chunks

    @staticmethod
    def _split_numbered_sections(chunks: list[str]) -> list[str]:
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
        paragraphs: list[str] = []
        current: list[str] = []
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
