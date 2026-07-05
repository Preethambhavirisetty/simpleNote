from __future__ import annotations

from typing import Sequence

from app.core.embeddings.remote import EmbeddingBatch, RemoteEmbeddingService
from app.core.feature_flags import is_enabled


REMOTE_EMBEDDINGS_FLAG = "ingestion.remote_embeddings"


class SharedEmbeddingClient:
    """Embedding facade that routes all calls to the remote RunPod embedding service."""

    def __init__(self, remote_service: RemoteEmbeddingService | None = None):
        self.remote_service = remote_service or RemoteEmbeddingService()
        self.events: list[str] = []

    @property
    def use_remote(self) -> bool:
        return self.remote_service.enabled and is_enabled(REMOTE_EMBEDDINGS_FLAG)

    def _assert_remote(self) -> None:
        if not self.use_remote:
            raise RuntimeError(
                "Remote embedding service is not available. "
                "Ensure EMBEDDING_MODEL_BASE is set and 'ingestion.remote_embeddings' flag is enabled."
            )

    def dimension(self) -> int:
        self._assert_remote()
        self.events.append("embedding dimension: remote")
        return self.remote_service.dimension()

    def embed_documents(self, texts: Sequence[str]) -> EmbeddingBatch:
        self._assert_remote()
        self.events.append(f"embedding documents: remote batch {len(texts)}")
        return self.remote_service.embed_hybrid(texts)

    def embed_queries(self, texts: Sequence[str]) -> EmbeddingBatch:
        self._assert_remote()
        self.events.append(f"embedding queries: remote batch {len(texts)}")
        return self.remote_service.embed_hybrid(texts)

    def embed_dense_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self._assert_remote()
        self.events.append(f"embedding dense documents: remote batch {len(texts)}")
        return self.remote_service.embed_dense(texts)

    def embed_dense_queries(self, texts: Sequence[str]) -> list[list[float]]:
        self._assert_remote()
        self.events.append(f"embedding dense queries: remote batch {len(texts)}")
        return self.remote_service.embed_dense(texts)
