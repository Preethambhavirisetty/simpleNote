from __future__ import annotations

import logging

from llama_index.core import Document as LlamaDocument
from llama_index.core import Settings
from llama_index.core.node_parser import SemanticSplitterNodeParser

from app.core.config import BREAKPOINT_PERCENTILE
from app.services.ingestion.processors.chunking.token_budget import within_chunk_budget
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

        semantic_parts = self._semantic_split(clean)
        if not semantic_parts:
            semantic_parts = [clean]

        parts = []
        for part in semantic_parts:
            parts.extend(self._window_chunker.split(part))

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
