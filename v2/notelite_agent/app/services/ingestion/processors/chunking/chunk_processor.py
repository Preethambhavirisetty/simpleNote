from __future__ import annotations

import logging
from dataclasses import dataclass

from app.services.ingestion.processors.chunking.heading_chunker import HeadingChunker
from app.services.ingestion.processors.chunking.heading_processor import HeadingProcessor
from app.services.ingestion.processors.chunking.post_processor import ChunkPostProcessor
from app.services.ingestion.processors.chunking.semantic_chunker import SemanticChunker
from app.services.ingestion.processors.chunking.token_budget import token_count
from app.services.ingestion.processors.chunking.validators import validate_chunk


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TextChunk:
    content: str
    chunk_id: str


class ChunkProcessor:
    """Orchestrates paragraph, heading, semantic, and postprocessing chunk stages."""

    def __init__(self):
        self.heading_chunker = HeadingChunker()
        self.semantic_chunker = SemanticChunker()
        self.heading_processor = HeadingProcessor(self.semantic_chunker)
        self.post_processor = ChunkPostProcessor()

    def split(self, text: str) -> list[str]:
        log.info("Chunking began...")

        prepared_text = self.heading_chunker.inject_numbered_line_breaks(text)
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

        final_chunks = self.post_processor.process(chunks)
        log.info(
            "Generated %d chunks (original=%d tokens, chunked=%d tokens)",
            len(final_chunks),
            token_count(prepared_text),
            sum(token_count(chunk) for chunk in final_chunks),
        )
        return final_chunks

    def process(self, text: str) -> list[TextChunk]:
        return [
            TextChunk(content=chunk, chunk_id=str(index))
            for index, chunk in enumerate(self.split(text))
        ]

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
