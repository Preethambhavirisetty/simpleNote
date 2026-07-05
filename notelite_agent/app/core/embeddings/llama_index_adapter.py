from __future__ import annotations

from typing import Sequence

from llama_index.core.embeddings import BaseEmbedding
from pydantic import PrivateAttr

from app.core.embeddings.remote import RemoteEmbeddingService


class RemoteOpenAIEmbedding(BaseEmbedding):
    """LlamaIndex BaseEmbedding adapter that routes to the remote RunPod endpoint.

    Why this adapter exists:
        SemanticSplitterNodeParser requires a BaseEmbedding subclass assigned to
        Settings.embed_model. The adapter is a thin bridge — it adds no overhead
        beyond the HTTP round-trip to RunPod, which is unavoidable regardless.

    Batching behaviour (optimal):
        SemanticSplitterNodeParser calls get_text_embedding_batch(sentences) which
        resolves to _get_text_embeddings (plural). That method sends all sentences
        in a single HTTP POST to /v1/embeddings, so a document with N sentences
        triggers exactly one network call during semantic splitting.
    """

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
