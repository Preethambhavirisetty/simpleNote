from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import httpx

from app.core.config import EMBEDDING_API_KEY, EMBEDDING_MODEL, EMBEDDING_MODEL_BASE, EMBEDDING_TIMEOUT


@dataclass(frozen=True)
class EmbeddingBatch:
    dense: list[list[float]]
    sparse: list[dict[str, list[float] | list[int]]]


# One connection pool shared by every RemoteEmbeddingService instance (the
# semantic chunker builds its own instance with a shorter timeout — timeouts are
# per-request, so instances can share the pool).
_http: httpx.Client | None = None


def _http_client() -> httpx.Client:
    global _http
    if _http is None:
        _http = httpx.Client()
    return _http


class RemoteEmbeddingService:
    """HTTP client for the RunPod embedding service."""

    def __init__(
        self,
        base_url: str = EMBEDDING_MODEL_BASE,
        model: str = EMBEDDING_MODEL,
        api_key: str = EMBEDDING_API_KEY,
        timeout: float = EMBEDDING_TIMEOUT,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self._dimension: int | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    def embed_hybrid(self, texts: Sequence[str]) -> EmbeddingBatch:
        clean_texts = [text or "" for text in texts]
        if not clean_texts:
            return EmbeddingBatch(dense=[], sparse=[])

        response = _http_client().post(
            f"{self.base_url}/embed",
            headers=self._headers(),
            json={"texts": clean_texts},
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()

        dense = data.get("dense_embeddings") or data.get("embeddings") or []
        sparse = data.get("sparse_embeddings") or []
        if len(dense) != len(clean_texts):
            raise ValueError(
                f"Embedding endpoint returned {len(dense)} dense vectors for {len(clean_texts)} texts."
            )
        if sparse and len(sparse) != len(clean_texts):
            raise ValueError(
                f"Embedding endpoint returned {len(sparse)} sparse vectors for {len(clean_texts)} texts."
            )
        if not sparse:
            sparse = [{"indices": [], "values": []} for _ in clean_texts]

        return EmbeddingBatch(dense=dense, sparse=sparse)

    def embed_dense(self, texts: Sequence[str]) -> list[list[float]]:
        clean_texts = [text or "" for text in texts]
        if not clean_texts:
            return []

        response = _http_client().post(
            f"{self.base_url}/v1/embeddings",
            headers=self._headers(),
            json={"model": self.model, "input": clean_texts},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return self._parse_openai_embeddings(response.json(), len(clean_texts))

    async def aembed_dense(self, texts: Sequence[str]) -> list[list[float]]:
        clean_texts = [text or "" for text in texts]
        if not clean_texts:
            return []

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/v1/embeddings",
                headers=self._headers(),
                json={"model": self.model, "input": clean_texts},
            )
        response.raise_for_status()
        return self._parse_openai_embeddings(response.json(), len(clean_texts))

    def dimension(self) -> int:
        if self._dimension is None:
            vectors = self.embed_dense(["dimension check"])
            if not vectors or not vectors[0]:
                raise ValueError("Embedding endpoint returned an empty dimension-check vector.")
            self._dimension = len(vectors[0])
        return self._dimension

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    @staticmethod
    def _parse_openai_embeddings(data: dict, expected_count: int) -> list[list[float]]:
        items = data.get("data") or []
        if len(items) != expected_count:
            raise ValueError(
                f"Embedding endpoint returned {len(items)} vectors for {expected_count} texts."
            )

        ordered = sorted(items, key=lambda item: item.get("index", 0))
        embeddings = [item.get("embedding") for item in ordered]
        if any(not embedding for embedding in embeddings):
            raise ValueError("Embedding endpoint returned an empty embedding.")
        return embeddings
