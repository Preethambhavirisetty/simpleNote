from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException

from app.services.ingestion.storage.vector_store import QdrantVectorStore

from .services import RetrievalActionServices


class RetrievalActionController:
    """Dispatch retrieval pipeline test actions by name while keeping payloads typed."""

    def __init__(self, vector_store: QdrantVectorStore):
        services = RetrievalActionServices(vector_store)
        self.handlers: dict[str, Callable[[Any], dict[str, Any]]] = {
            "retrieval.intent": services.intent,
            "retrieval.context": services.context,
            "retrieval.prompt": services.prompt,
        }

    def run(self, action_name: str, payload: Any) -> dict[str, Any]:
        handler = self.handlers.get(action_name)
        if handler is None:
            raise HTTPException(status_code=400, detail=f"Unsupported retrieval action: {action_name}")

        try:
            return handler(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
