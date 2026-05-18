from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import StreamingResponse

from app.services.chat.schema import ChatRequest
from app.services.chat.streaming import StreamingService
from app.shared.llm import llm_call_general
from app.shared.schema import ApiResponse


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])
streaming_service = StreamingService()


@router.post("/completions", response_model=ApiResponse[dict])
def chat_completion(payload: dict[str, Any] = Body(...)):
    """Non-streaming OpenAI-compatible chat completion proxy."""
    messages = payload.get("messages")
    if not messages or not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="'messages' must be a non-empty list")

    try:
        response = llm_call_general(messages)
        return ApiResponse.ok({"response": response})
    except httpx.HTTPError as exc:
        log.warning("chat completion failed", exc_info=True)
        raise HTTPException(status_code=503, detail="Inference service error") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Stream assistant output as SSE events."""
    return streaming_service.stream(request)
