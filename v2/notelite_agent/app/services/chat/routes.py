from __future__ import annotations

import logging
import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import LLM_REASONER_MODEL
from app.core.dependencies import get_qdrant_store, require_api_key
from app.services.chat.schema import (
    ChatCompletionData,
    ChatCompletionRequest,
    ChatRequest,
    ConversationHistoryData,
    ConversationHistoryRequest,
)
from app.services.chat.streaming import StreamingService
from app.services.ingestion.storage.vector_store import QdrantVectorStore
from app.shared.backend_conversation_client import BackendConversationClient
from app.shared.llm import llm_call_general
from app.shared.schema import ApiResponse


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"], dependencies=[Depends(require_api_key)])
_streaming_service = StreamingService()


@router.post("/completions", response_model=ApiResponse[ChatCompletionData], summary="Create a direct chat completion")
def chat_completion(payload: ChatCompletionRequest):
    """Non-streaming LLM proxy. Does not perform retrieval or manage conversations."""
    messages = [message.model_dump() for message in payload.messages]

    try:
        response = llm_call_general(messages, model=LLM_REASONER_MODEL)
        return ApiResponse.ok({"response": response})
    except httpx.HTTPError as exc:
        log.warning("chat completion failed", exc_info=True)
        raise HTTPException(status_code=503, detail="Inference service error") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/conversation-history", response_model=ApiResponse[ConversationHistoryData], summary="Fetch conversation history")
def get_conversation_history(request: ConversationHistoryRequest):
    """Fetch raw stored messages without creating a chat turn."""
    client = BackendConversationClient()
    messages = client.get_messages(request.user_id, request.conversation_id)
    return ApiResponse.ok({
        "conversation_id": request.conversation_id,
        "messages": messages,
        "events": client.drain_events(),
    })


@router.post(
    "/stream",
    summary="Stream a RAG chat response",
    description="Streams Server-Sent Events: meta, delta, error, and done.",
    responses={200: {"description": "SSE chat stream", "content": {"text/event-stream": {}}}},
)
def chat_stream(
    request: ChatRequest,
    vector_store: QdrantVectorStore = Depends(get_qdrant_store),
) -> StreamingResponse:
    """Stream assistant output as SSE with RAG context from the user's notes."""
    return _streaming_service.stream(request, vector_store=vector_store)
