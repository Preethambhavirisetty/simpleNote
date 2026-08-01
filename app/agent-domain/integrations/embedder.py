from __future__ import annotations

from functools import lru_cache

from sentence_transformers import SentenceTransformer

from config import EMBEDDING_DEVICE, EMBEDDING_MODEL


@lru_cache(maxsize=1)
def get_embedder() -> SentenceTransformer:
    """Return the single embedding model instance used by this process."""
    return SentenceTransformer(EMBEDDING_MODEL, device=EMBEDDING_DEVICE)


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []

    embeddings = get_embedder().encode(
        texts,
        batch_size=32,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return embeddings.tolist()
