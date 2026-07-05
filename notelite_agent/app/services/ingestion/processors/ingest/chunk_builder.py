from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Sequence

from app.core.config import INDEX_CODE_CHUNKS, INDEX_JSON_CHUNKS, MIN_INDEXABLE_TOKENS
from app.services.ingestion.processors.chunking.chunk_types import ChunkType
from app.services.ingestion.processors.chunking.token_budget import token_count
from app.services.ingestion.processors.ingest.models import IndexChunk
from app.services.ingestion.processors.keywords.keyword_processor import ChunkKeywordResult
from app.services.ingestion.processors.text_normalization import (
    augment_markdown_table,
    normalize_markdown_tables_for_terms,
)


class ChunkBuilder:
    """Build ordered, vendor-neutral index chunks from keyword-enriched chunks."""

    def __init__(self, data: dict[str, Any], document_id: str):
        self.data = data
        self.document_id = document_id
        self.events: list[str] = []

    def build(self, chunks: Sequence[ChunkKeywordResult]) -> list[IndexChunk]:
        """Convert ordered ChunkKeywordResult input into ordered IndexChunk output."""
        self.events = [f"chunk build started: {len(chunks)} chunks"]
        total = len(chunks)
        built = [self._build_chunk(chunk, index, total) for index, chunk in enumerate(chunks)]
        linked = [
            replace(
                chunk,
                prev_chunk_id=built[index - 1].chunk_id if index > 0 else None,
                next_chunk_id=built[index + 1].chunk_id if index + 1 < total else None,
            )
            for index, chunk in enumerate(built)
        ]
        skipped = sum(chunk.skip_indexing for chunk in linked)
        self.events.append(f"chunk build completed: {total - skipped} indexable, {skipped} skipped")
        return linked

    def _build_chunk(self, chunk: ChunkKeywordResult, index: int, total: int) -> IndexChunk:
        metadata = {**self._shared_metadata(), **chunk.metadata}
        metadata.setdefault("has_heading_context", bool(metadata.get("heading_context")))
        metadata.setdefault("token_count", token_count(chunk.content))
        metadata.setdefault("char_count", len(chunk.content))
        embed_text = self._embedding_text(chunk, metadata)
        metadata["embed_text_token_count"] = token_count(embed_text) if embed_text else 0
        skip_reason = self._skip_reason(chunk.chunk_type, metadata, embed_text)
        return IndexChunk(
            chunk_id=chunk.chunk_id,
            document_id=self.document_id,
            chunk_index=chunk.chunk_index if chunk.total_chunks else index,
            total_chunks=chunk.total_chunks or total,
            chunk_type=chunk.chunk_type,
            content=chunk.content,
            embed_text=embed_text,
            skip_indexing=bool(skip_reason),
            skip_reason=skip_reason,
            keywords=list(chunk.keywords),
            entities=list(chunk.entities),
            metadata=metadata,
        )

    def _embedding_text(self, chunk: ChunkKeywordResult, metadata: dict[str, Any]) -> str:
        content = self._normalize_whitespace(chunk.content)
        heading = str(metadata.get("heading_context") or "").strip()
        if chunk.chunk_type == ChunkType.TABLE.value:
            augmented = augment_markdown_table(chunk.content, heading)
            if augmented:
                return self._normalize_whitespace(augmented)
            self.events.append(f"table augmentation fallback: chunk={chunk.chunk_id}")
            return self._normalize_whitespace(normalize_markdown_tables_for_terms(chunk.content))
        if chunk.chunk_type in {
            ChunkType.FAQ.value, ChunkType.GLOSSARY.value, ChunkType.CONTACT.value,
            ChunkType.ADDRESS.value, ChunkType.CODE.value, ChunkType.JSON.value,
        }:
            return content
        if content.startswith("#") or not heading or not metadata.get("has_heading_context"):
            return content
        return self._normalize_whitespace(f"{heading}\n\n{content}")

    @staticmethod
    def _skip_reason(chunk_type: str, metadata: dict[str, Any], embed_text: str) -> str:
        if not embed_text.strip():
            return "empty_embed_text"
        if chunk_type == ChunkType.CODE.value and not INDEX_CODE_CHUNKS:
            return "structural:code"
        if chunk_type == ChunkType.JSON.value and not INDEX_JSON_CHUNKS:
            return "structural:json"
        if chunk_type == ChunkType.HEADING_ONLY.value:
            return "structural:heading_only"
        quality_reason = str(metadata.get("skip_keywords_reason") or "").lower()
        if "ocr" in quality_reason:
            return f"quality:{quality_reason}"
        if int(metadata.get("token_count") or 0) < MIN_INDEXABLE_TOKENS:
            return f"quality:min_tokens<{MIN_INDEXABLE_TOKENS}"
        return ""

    def _shared_metadata(self) -> dict[str, Any]:
        raw_tags = self.data.get("tags") or []
        tags = raw_tags if isinstance(raw_tags, list) else [str(raw_tags)]
        return {
            "doc_id": self.document_id,
            "user_id": self.data.get("user_id"),
            "folder_id": self.data.get("folder_id"),
            "note_id": self.data.get("note_id"),
            "folder_title": self.data.get("folder_title", ""),
            "note_title": self.data.get("note_title", ""),
            "description": self.data.get("description", ""),
            "tags": ",".join(str(tag) for tag in tags if str(tag).strip()),
        }

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        clean = re.sub(r"[ \t]+", " ", text.strip())
        return re.sub(r"\n{3,}", "\n\n", clean)
