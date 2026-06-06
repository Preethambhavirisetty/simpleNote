from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.ingestion.processors.chunking.chunk_types import ChunkType, classify_chunk_type
from app.services.ingestion.processors.chunking.semantic_chunker import SemanticChunker
from app.services.ingestion.processors.chunking.token_budget import within_chunk_budget
from app.services.ingestion.processors.chunking.chunk_classifier import split_into_typed_chunks
from app.services.ingestion.processors.text_normalization import repair_ocr_hyphenation


@dataclass(frozen=True)
class TextChunk:
    content: str
    chunk_id: str
    chunk_type: str = ChunkType.CONTENT.value
    metadata: dict[str, Any] = field(default_factory=dict)


class ChunkProcessor:
    """Build typed structural chunks and semantically split substantial prose."""

    def __init__(self):
        self.semantic_chunker = SemanticChunker()

    def process(self, text: str) -> list[TextChunk]:
        normalized_text = repair_ocr_hyphenation(text)
        chunks = split_into_typed_chunks(normalized_text)

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
        return self._merge_compatible_section_chunks(output)

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

        return [
            TextChunk(chunk.content, str(index), chunk.chunk_type, dict(chunk.metadata))
            for index, chunk in enumerate(merged)
        ]
