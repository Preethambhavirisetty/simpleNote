from __future__ import annotations

from app.services.ingestion.processors.chunking.semantic_chunker import SemanticChunker
from app.services.ingestion.processors.chunking.token_budget import within_chunk_budget
from app.services.ingestion.processors.chunking.validators import validate_chunk


class HeadingProcessor:
    """Processes heading-derived parts while preserving merge behavior."""

    def __init__(self, semantic_chunker: SemanticChunker):
        self.semantic_chunker = semantic_chunker

    def process(
        self,
        heading_parts: list[str],
        chunks: list[str],
        pending_paragraph: str,
    ) -> str:
        pending_chunk = ""

        for part in heading_parts:
            candidate = f"{pending_chunk}\n{part}".strip() if pending_chunk else part

            if within_chunk_budget(candidate):
                pending_chunk = self._handle_candidate(candidate, chunks)
                continue

            if pending_chunk and validate_chunk(pending_chunk) == "VALID":
                chunks.append(pending_chunk)

            if within_chunk_budget(part):
                pending_chunk = self._handle_candidate(part, chunks)
            else:
                chunks.extend(self.semantic_chunker.split(part))
                pending_chunk = ""

        return self._flush_pending_chunk(pending_chunk, chunks, pending_paragraph)

    @staticmethod
    def _handle_candidate(candidate: str, chunks: list[str]) -> str:
        verdict = validate_chunk(candidate)
        if verdict == "DISCARD":
            return ""
        if verdict == "VALID":
            chunks.append(candidate)
            return ""
        return candidate

    @staticmethod
    def _flush_pending_chunk(
        pending_chunk: str,
        chunks: list[str],
        pending_paragraph: str,
    ) -> str:
        if not pending_chunk:
            return pending_paragraph

        verdict = validate_chunk(pending_chunk)
        if verdict == "VALID":
            chunks.append(pending_chunk)
        elif verdict == "NEEDS_MERGE":
            return (
                f"{pending_paragraph}\n{pending_chunk}".strip()
                if pending_paragraph
                else pending_chunk
            )

        return pending_paragraph
