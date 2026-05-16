from fastapi import APIRouter, Body
from typing import Any
from app.shared.llm import llm_call_general

router = APIRouter(prefix="/api/chat")

@router.post("/completions")
async def chat_completion(
    payload: dict[str, Any] = Body(...)
):
    resp = llm_call_general(payload['messages'])
    return {"message": resp}

@router.post("/stream")
async def chat_stream(payload):
    return {"message": "success"}
