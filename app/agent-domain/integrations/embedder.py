"""Dense embeddings from the remote inference host.

Served over HTTP rather than loaded in-process. The service embeds a handful of
short strings on catalog load and one question per search - work that does not
justify carrying torch, a model download, and a GPU-shaped memory footprint in
a container that otherwise reads YAML.

Same endpoint and payload as orchestrator/app/core/embeddings/remote.py, so the
two services stay on one model without coordinating.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from config import (
    EMBEDDING_API_KEY,
    EMBEDDING_MODEL,
    EMBEDDING_MODEL_BASE,
    EMBEDDING_TIMEOUT,
)

log = logging.getLogger(__name__)

# One pool for the process; timeouts are per request.
_http: httpx.Client | None = None


class EmbeddingsUnavailableError(RuntimeError):
    """No embedding endpoint is configured, or it could not be reached."""


def embeddings_available() -> bool:
    return bool(EMBEDDING_MODEL_BASE)


def _http_client() -> httpx.Client:
    global _http
    if _http is None:
        _http = httpx.Client()
    return _http


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if EMBEDDING_API_KEY:
        headers["Authorization"] = f"Bearer {EMBEDDING_API_KEY}"
    return headers


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    if not embeddings_available():
        raise EmbeddingsUnavailableError(
            "no embedding endpoint configured: set EC2_INFERENCE_BASE_IP or "
            "EMBEDDING_MODEL_BASE"
        )

    try:
        response = _http_client().post(
            f"{EMBEDDING_MODEL_BASE}/v1/embeddings",
            headers=_headers(),
            json={"model": EMBEDDING_MODEL, "input": [text or "" for text in texts]},
            timeout=EMBEDDING_TIMEOUT,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise EmbeddingsUnavailableError(
            f"embedding request to {EMBEDDING_MODEL_BASE} failed: {exc}"
        ) from exc

    return _parse(response.json(), len(texts))


def _parse(payload: Any, expected: int) -> list[list[float]]:
    """Read the OpenAI embeddings shape, honouring the returned index order."""
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or len(data) != expected:
        raise EmbeddingsUnavailableError(
            f"embedding endpoint returned {len(data) if isinstance(data, list) else '?'} "
            f"vectors for {expected} inputs"
        )

    vectors: list[list[float]] = [[] for _ in range(expected)]
    for position, item in enumerate(data):
        index = item.get("index", position) if isinstance(item, dict) else position
        embedding = item.get("embedding") if isinstance(item, dict) else None
        if not isinstance(embedding, list) or not (0 <= index < expected):
            raise EmbeddingsUnavailableError("embedding endpoint returned a malformed item")
        vectors[index] = [float(value) for value in embedding]

    return vectors
