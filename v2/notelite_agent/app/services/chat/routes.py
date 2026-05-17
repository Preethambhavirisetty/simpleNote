import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from app.shared.llm import llm_call_general
from app.shared.schema import ApiResponse


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat")


@router.post("/completions", response_model=ApiResponse[dict])
def chat_completion(
    payload: dict[str, Any] = Body(...),
):
    """Non-streaming chat completion (retrieval pipeline not yet wired)."""
    messages = payload.get("messages")
    if not messages or not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="'messages' must be a non-empty list")

    try:
        response = llm_call_general(messages)
        return ApiResponse.ok({"response": response})
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/stream", response_model=ApiResponse[dict])
async def chat_stream(payload: dict[str, Any] = Body(...)):
    """Streaming chat endpoint — not yet implemented."""
    raise HTTPException(status_code=501, detail="Streaming not yet implemented")
