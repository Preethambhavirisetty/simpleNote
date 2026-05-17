from __future__ import annotations

from typing import Sequence

from llama_index.core.embeddings import BaseEmbedding
from pydantic import PrivateAttr

from app.core.embeddings.remote import RemoteEmbeddingService


class RemoteOpenAIEmbedding(BaseEmbedding):
    """LlamaIndex-compatible dense embedding adapter for semantic splitting."""

    _service: RemoteEmbeddingService = PrivateAttr()

    def __init__(self, service: RemoteEmbeddingService, **kwargs):
        super().__init__(**kwargs)
        self._service = service

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._embed([text])[0]

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._embed([query])[0]

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return (await self._aembed([text]))[0]

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return (await self._aembed([query]))[0]

    def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        return self._service.embed_dense(texts)

    async def _aembed(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._service.aembed_dense(texts)
