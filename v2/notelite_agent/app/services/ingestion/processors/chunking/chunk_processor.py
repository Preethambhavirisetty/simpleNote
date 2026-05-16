from __future__ import annotations

import logging
from dataclasses import dataclass

from app.services.ingestion.processors.chunking.heading_chunker import HeadingChunker
from app.services.ingestion.processors.chunking.heading_processor import HeadingProcessor
from app.services.ingestion.processors.chunking.post_processor import ChunkPostProcessor
from app.services.ingestion.processors.chunking.semantic_chunker import SemanticChunker
from app.services.ingestion.processors.chunking.token_budget import (
    token_count,
    within_chunk_budget,
)
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
        paragraphs = [p.strip() for p in prepared_text.split("\n\n") if p.strip()]

        chunks = []
        pending_paragraph = ""

        for paragraph in paragraphs:
            current = f"{pending_paragraph}\n{paragraph}".strip() if pending_paragraph else paragraph
            pending_paragraph = ""

            if within_chunk_budget(current):
                pending_paragraph = self._handle_small_paragraph(current, chunks)
                continue

            heading_parts = self.heading_chunker.split(current)
            if len(heading_parts) > 1:
                pending_paragraph = self.heading_processor.process(
                    heading_parts,
                    chunks,
                    pending_paragraph,
                )
            else:
                chunks.extend(self.semantic_chunker.split(current))

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
    def _handle_small_paragraph(paragraph: str, chunks: list[str]) -> str:
        verdict = validate_chunk(paragraph)
        if verdict == "VALID":
            chunks.append(paragraph)
            return ""
        if verdict == "NEEDS_MERGE":
            return paragraph
        return ""
