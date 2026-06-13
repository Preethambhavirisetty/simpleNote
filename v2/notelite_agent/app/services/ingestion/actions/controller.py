from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException

from app.services.chat.actions.controller import RetrievalActionController
from app.services.ingestion.storage.vector_store import QdrantVectorStore

from .schema import PipelineActionRequest, PipelineActionResponse
from .services import IngestionActionServices


class IngestionActionController:
    """Dispatch ingestion pipeline test actions by name while keeping payloads typed."""

    def __init__(self, vector_store: QdrantVectorStore | None = None):
        services = IngestionActionServices(vector_store)
        self.handlers: dict[str, Callable[[Any], dict[str, Any]]] = {
            "ingestion.chunk": services.chunk,
            "ingestion.keywords": services.keywords,
            "ingestion.chunk_build": services.chunk_build,
            "ingestion.index_chunks": services.index_chunks,
            "ingestion.summary": services.summary,
            "ingestion.questions": services.questions,
            "ingestion.summary_build": services.summary_build,
            "ingestion.index_summary": services.index_summary,
            "ingestion.documents": services.documents,
        }

    def run(self, action_name: str, payload: Any) -> dict[str, Any]:
        handler = self.handlers.get(action_name)
        if handler is None:
            raise HTTPException(status_code=400, detail=f"Unsupported ingestion action: {action_name}")

        try:
            return handler(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc


class PipelineActionController:
    """Dispatch typed ingestion and retrieval pipeline actions from one endpoint."""

    def __init__(self, vector_store: QdrantVectorStore):
        self._controllers = {
            "ingestion": IngestionActionController(vector_store),
            "retrieval": RetrievalActionController(vector_store),
        }

    def run(self, request: PipelineActionRequest) -> PipelineActionResponse:
        namespace = request.action_name.split(".", 1)[0]
        controller = self._controllers.get(namespace)
        if controller is None:
            raise HTTPException(status_code=400, detail=f"Unsupported action: {request.action_name}")

        result = controller.run(request.action_name, request.payload)
        return PipelineActionResponse(action_name=request.action_name, result=result)
