from __future__ import annotations

import logging
import time

from llama_index.core import Document as LlamaDocument
from llama_index.core import Settings
from llama_index.core.node_parser import SemanticSplitterNodeParser

from app.core.config import (
    BREAKPOINT_PERCENTILE,
    MAX_CHUNK_SIZE,
    SEMANTIC_CHUNKING_FAILURE_COOLDOWN,
    SEMANTIC_CHUNKING_TIMEOUT,
)
from app.core.embeddings import RemoteEmbeddingService, RemoteOpenAIEmbedding
from app.services.ingestion.processors.chunking.token_budget import token_count, within_chunk_budget
from app.services.ingestion.processors.chunking.validators import (
    is_fenced_code_block,
    split_preserving_fenced_code_blocks,
)
from app.services.ingestion.processors.chunking.window_chunker import WindowChunker


log = logging.getLogger(__name__)


class SemanticChunker:
    """Semantic splitter with a bounded remote call and local safety net."""

    _remote_disabled_until = 0.0

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

        local_limit = max(soft_limit, (token_count(clean) + 2) // 3)
        parts: list[str] = []
        current: list[str] = []
        current_tokens = 0
        for sentence in sentences:
            sentence_tokens = token_count(sentence)
            if current and current_tokens + sentence_tokens > local_limit:
                parts.append(" ".join(current).strip())
                current = []
                current_tokens = 0
            current.append(sentence)
            current_tokens += sentence_tokens
        if current:
            parts.append(" ".join(current).strip())
        if len(parts) > 1 and token_count(parts[-1]) < max(1, local_limit // 2):
            candidate = f"{parts[-2]} {parts[-1]}".strip()
            if within_chunk_budget(candidate):
                parts[-2:] = [candidate]
        return parts

    def _semantic_split(self, text: str) -> list[str]:
        if time.monotonic() < type(self)._remote_disabled_until:
            return []

        try:
            splitter = self._get_splitter()
            nodes = splitter.get_nodes_from_documents([LlamaDocument(text=text)])
            return [node.get_content().strip() for node in nodes if node.get_content().strip()]
        except Exception as exc:
            type(self)._remote_disabled_until = time.monotonic() + SEMANTIC_CHUNKING_FAILURE_COOLDOWN
            log.warning(
                "Semantic splitting failed (%s); using local fallback for %.0fs.",
                type(exc).__name__,
                SEMANTIC_CHUNKING_FAILURE_COOLDOWN,
            )
            return []

    def _get_splitter(self) -> SemanticSplitterNodeParser:
        if self._splitter is None:
            configured_model = getattr(Settings, "embed_model", None)
            if not configured_model:
                raise RuntimeError("No initialized embedding model is available for semantic chunking.")

            service = RemoteEmbeddingService(timeout=SEMANTIC_CHUNKING_TIMEOUT)
            embed_model = (
                RemoteOpenAIEmbedding(service=service)
                if service.enabled and isinstance(configured_model, RemoteOpenAIEmbedding)
                else configured_model
            )
            self._splitter = SemanticSplitterNodeParser(
                embed_model=embed_model,
                breakpoint_percentile_threshold=BREAKPOINT_PERCENTILE,
                buffer_size=1,
            )
        return self._splitter
