from __future__ import annotations

import logging

from llama_index.core import Document as LlamaDocument
from llama_index.core import Settings
from llama_index.core.node_parser import SemanticSplitterNodeParser

from app.core.config import BREAKPOINT_PERCENTILE, MAX_CHUNK_SIZE
from app.services.ingestion.processors.chunking.token_budget import token_count, within_chunk_budget
from app.services.ingestion.processors.chunking.validators import (
    is_fenced_code_block,
    split_preserving_fenced_code_blocks,
)
from app.services.ingestion.processors.chunking.window_chunker import WindowChunker


log = logging.getLogger(__name__)


class SemanticChunker:
    """Semantic splitter with window splitting as a safety net."""

    def __init__(self, window_chunker: WindowChunker | None = None):
        self._splitter: SemanticSplitterNodeParser | None = None
        self._window_chunker = window_chunker or WindowChunker()

    def split(self, text: str) -> list[str]:
        clean = text.strip()
        if not clean:
            return []
        if within_chunk_budget(clean):
            return [clean]

        parts: list[str] = []
        for segment in split_preserving_fenced_code_blocks(clean):
            if is_fenced_code_block(segment):
                parts.append(segment.strip())
                continue

            semantic_parts = self._semantic_split(segment)
            if not semantic_parts:
                semantic_parts = [segment]

            for part in semantic_parts:
                parts.extend(self._window_chunker.split(part))

        return parts

    def split_prose(self, text: str) -> list[str]:
        """Semantically split substantial prose while keeping short prose intact."""
        clean = text.strip()
        if not clean:
            return []

        soft_limit = max(1, MAX_CHUNK_SIZE // 16)
        if token_count(clean) <= soft_limit:
            return [clean]

        sentences = self._window_chunker._split_sentences(clean)
        minimum_semantic_sentences = max(6, MAX_CHUNK_SIZE // 120)
        if len(sentences) < minimum_semantic_sentences:
            return [clean]

        semantic_parts = self._semantic_split(clean)
        if len(semantic_parts) > 1:
            return semantic_parts

        parts: list[str] = []
        current: list[str] = []
        current_tokens = 0
        for sentence in sentences:
            sentence_tokens = token_count(sentence)
            if current and current_tokens + sentence_tokens > soft_limit:
                parts.append(" ".join(current).strip())
                current = []
                current_tokens = 0
            current.append(sentence)
            current_tokens += sentence_tokens
        if current:
            parts.append(" ".join(current).strip())
        return parts

    def _semantic_split(self, text: str) -> list[str]:
        try:
            splitter = self._get_splitter()
            nodes = splitter.get_nodes_from_documents([LlamaDocument(text=text)])
            return [node.get_content().strip() for node in nodes if node.get_content().strip()]
        except Exception:
            log.debug("Semantic splitting failed; falling back to window split.", exc_info=True)
            return []

    def _get_splitter(self) -> SemanticSplitterNodeParser:
        if self._splitter is None:
            if not getattr(Settings, "embed_model", None):
                raise RuntimeError(
                    "LlamaIndex settings are not initialized. "
                    "Call init_llama_index_settings() once at application startup."
                )
            self._splitter = SemanticSplitterNodeParser(
                embed_model=Settings.embed_model,
                breakpoint_percentile_threshold=BREAKPOINT_PERCENTILE,
                buffer_size=1,
            )
        return self._splitter
