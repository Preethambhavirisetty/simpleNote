from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.services.chat.pipeline.retrieval_pipeline import RetrievalResult, run_retrieval
from app.services.ingestion.storage.vector_store import QdrantVectorStore


def retrieve_context_result(
    vector_store: QdrantVectorStore,
    query: str,
    user_id: str,
    k: int,
    role: str,
    history: Sequence[Mapping[str, str]] | None = None,
) -> RetrievalResult:
    """Run retrieval and return the complete structured result."""
    return run_retrieval(vector_store, query, user_id, k, role, history)


def retrieve_context(
    vector_store: QdrantVectorStore,
    query: str,
    user_id: str,
    k: int,
    role: str,
    history: Sequence[Mapping[str, str]] | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Return context excerpts and UI references for chat streaming."""
    result = retrieve_context_result(vector_store, query, user_id, k, role, history)
    return result.context_texts, result.references


def retrieve_context_diagnostics(
    vector_store: QdrantVectorStore,
    query: str,
    user_id: str,
    k: int,
    role: str,
    history: Sequence[Mapping[str, str]] | None = None,
) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
    """Return retrieval output plus inspectable stage diagnostics."""
    result = retrieve_context_result(vector_store, query, user_id, k, role, history)
    return result.context_texts, result.references, result.diagnostics
