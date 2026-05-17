from __future__ import annotations

from typing import Sequence

from llama_index.core import Settings

from app.core.embeddings.remote import EmbeddingBatch, RemoteEmbeddingService
from app.core.feature_flags import is_enabled


REMOTE_EMBEDDINGS_FLAG = "ingestion.remote_embeddings"


class SharedEmbeddingClient:
    """Shared embedding facade for local fallback or remote RunPod embeddings."""

    def __init__(self, remote_service: RemoteEmbeddingService | None = None):
        self.remote_service = remote_service or RemoteEmbeddingService()
        self.events: list[str] = []

    @property
    def use_remote(self) -> bool:
        return self.remote_service.enabled and is_enabled(REMOTE_EMBEDDINGS_FLAG)

    def dimension(self) -> int:
        if self.use_remote:
            self.events.append("embedding dimension: remote")
            return self.remote_service.dimension()

        self.events.append("embedding dimension: local")
        return len(Settings.embed_model.get_text_embedding("dimension check"))

    def embed_documents(self, texts: Sequence[str]) -> EmbeddingBatch:
        if self.use_remote:
            self.events.append(f"embedding documents: remote batch {len(texts)}")
            return self.remote_service.embed_hybrid(texts)

        self.events.append(f"embedding documents: local batch {len(texts)}")
        dense = [Settings.embed_model.get_text_embedding(text) for text in texts]
        sparse = [Settings.sparse_model.get_text_embedding(text) for text in texts]
        return EmbeddingBatch(dense=dense, sparse=sparse)

    def embed_queries(self, texts: Sequence[str]) -> EmbeddingBatch:
        if self.use_remote:
            self.events.append(f"embedding queries: remote batch {len(texts)}")
            return self.remote_service.embed_hybrid(texts)

        self.events.append(f"embedding queries: local batch {len(texts)}")
        dense = [Settings.embed_model.get_query_embedding(text) for text in texts]
        sparse = [Settings.sparse_model.get_query_embedding(text) for text in texts]
        return EmbeddingBatch(dense=dense, sparse=sparse)

    def embed_dense_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if self.use_remote:
            self.events.append(f"embedding dense documents: remote batch {len(texts)}")
            return self.remote_service.embed_dense(texts)

        self.events.append(f"embedding dense documents: local batch {len(texts)}")
        return [Settings.embed_model.get_text_embedding(text) for text in texts]

    def embed_dense_queries(self, texts: Sequence[str]) -> list[list[float]]:
        if self.use_remote:
            self.events.append(f"embedding dense queries: remote batch {len(texts)}")
            return self.remote_service.embed_dense(texts)

        self.events.append(f"embedding dense queries: local batch {len(texts)}")
        return [Settings.embed_model.get_query_embedding(text) for text in texts]
