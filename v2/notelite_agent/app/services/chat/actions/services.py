from __future__ import annotations

from typing import Any

from app.services.chat import retriever
from app.services.ingestion.storage.vector_store import QdrantVectorStore
from app.shared.prompts import prompt

from .schema import PromptPayload, RetrievalPayload


class RetrievalActionServices:
    """Side-effect-aware runners for retrieval and prompt assembly stages."""

    def __init__(self, vector_store: QdrantVectorStore):
        self.vector_store = vector_store

    def context(self, payload: RetrievalPayload) -> dict[str, Any]:
        history = [message.model_dump() for message in payload.history]
        context_texts, references, diagnostics = retriever.retrieve_context_diagnostics(
            self.vector_store,
            payload.query,
            payload.user_id,
            payload.k,
            payload.role,
            history,
        )
        return {
            "context_texts": context_texts,
            "references": references,
            "diagnostics": diagnostics,
        }

    def prompt(self, payload: PromptPayload) -> dict[str, Any]:
        history = [message.model_dump() for message in payload.history]
        retrieval_result: dict[str, Any] | None = None
        context_texts = payload.context_texts
        if context_texts is None:
            retrieval_result = self.context(payload)
            context_texts = retrieval_result["context_texts"]

        messages = prompt.build_messages(payload.query, history, context_texts)
        return {
            "retrieval": retrieval_result,
            "history": history,
            "messages": messages,
            "prompt_tokens_estimate": prompt.estimate_prompt_tokens(messages),
        }
