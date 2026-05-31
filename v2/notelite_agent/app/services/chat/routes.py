from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import LLM_REASONER_MODEL
from app.core.dependencies import get_qdrant_store
from app.services.chat import retriever
from app.services.chat.schema import ChatRequest, ChatStageRequest, ConversationHistoryRequest
from app.services.chat.streaming import StreamingService
from app.services.ingestion.storage.vector_store import QdrantVectorStore
from app.shared.backend_conversation_client import BackendConversationClient
from app.shared.llm import llm_call_general
from app.shared.prompts import prompt
from app.shared.schema import ApiResponse


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])
_streaming_service = StreamingService()


@router.post("/completions", response_model=ApiResponse[dict])
def chat_completion(payload: dict[str, Any] = Body(...)):
    """Non-streaming LLM proxy. Does not perform retrieval or manage conversations."""
    messages = payload.get("messages")
    if not messages or not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="'messages' must be a non-empty list")

    try:
        response = llm_call_general(messages, model=LLM_REASONER_MODEL)
        return ApiResponse.ok({"response": response})
    except httpx.HTTPError as exc:
        log.warning("chat completion failed", exc_info=True)
        raise HTTPException(status_code=503, detail="Inference service error") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/stages/retrieval", response_model=ApiResponse[dict])
def retrieval_stage(
    request: ChatStageRequest,
    vector_store: QdrantVectorStore = Depends(get_qdrant_store),
):
    """Inspect summary search, chunk search, reranking, and context selection."""
    query = _require_query(request.query)
    _, _, diagnostics = retriever.retrieve_context_diagnostics(
        vector_store, query, request.user_id, request.k, request.role,
    )
    return ApiResponse.ok(diagnostics)


@router.post("/stages/prompt", response_model=ApiResponse[dict])
def prompt_stage(
    request: ChatStageRequest,
    vector_store: QdrantVectorStore = Depends(get_qdrant_store),
):
    """Inspect the exact messages assembled after retrieval."""
    query = _require_query(request.query)
    context_texts, _, diagnostics = retriever.retrieve_context_diagnostics(
        vector_store, query, request.user_id, request.k, request.role,
    )
    history = [message.model_dump() for message in request.history]
    messages = prompt.build_messages(query, history, context_texts)
    return ApiResponse.ok({
        "retrieval": diagnostics,
        "history": history,
        "messages": messages,
        "prompt_tokens_estimate": prompt.estimate_prompt_tokens(messages),
    })


@router.post("/conversation-history", response_model=ApiResponse[dict])
def get_conversation_history(request: ConversationHistoryRequest):
    """Fetch raw stored messages without creating a chat turn."""
    client = BackendConversationClient()
    messages = client.get_messages(request.user_id, request.conversation_id)
    return ApiResponse.ok({
        "conversation_id": request.conversation_id,
        "messages": messages,
        "events": client.drain_events(),
    })


@router.post("/stream")
def chat_stream(
    request: ChatRequest,
    vector_store: QdrantVectorStore = Depends(get_qdrant_store),
) -> StreamingResponse:
    """Stream assistant output as SSE with RAG context from the user's notes."""
    return _streaming_service.stream(request, vector_store=vector_store)


def _require_query(query: str) -> str:
    query = query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty.")
    return query
