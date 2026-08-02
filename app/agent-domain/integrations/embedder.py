"""Sentence embeddings for playbook search.

Optional by design. Semantic search only runs when the catalog outgrows
PLAYBOOK_CANDIDATE_LIMIT, so a deployment below that limit should not have to
carry torch and its dependency tree. The import is therefore deferred and its
absence is a clear error at the point of use, not an ImportError at boot.
"""

from __future__ import annotations

from functools import lru_cache

from config import EMBEDDING_DEVICE, EMBEDDING_MODEL


class EmbeddingsUnavailableError(RuntimeError):
    """sentence-transformers is not installed in this deployment."""


def embeddings_available() -> bool:
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        return False
    return True


@lru_cache(maxsize=1)
def get_embedder():
    """Return the single embedding model instance used by this process."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise EmbeddingsUnavailableError(
            "semantic playbook search needs sentence-transformers: "
            "pip install -r requirements-embeddings.txt"
        ) from exc

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
