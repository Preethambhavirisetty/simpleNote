from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.chat.schema import ChatHistoryMessage


class IntentPayload(BaseModel):
    query: str = Field(..., min_length=1)


class RetrievalPayload(BaseModel):
    query: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1)
    k: int = Field(5, ge=1, le=50)
    role: Literal["user", "admin"] = "user"
    history: list[ChatHistoryMessage] = Field(default_factory=list)


class PromptPayload(RetrievalPayload):
    context_texts: list[str] | None = None


class IntentActionRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "action_name": "retrieval.intent",
            "payload": {"query": "compare my January and March notes"},
        }
    })

    action_name: Literal["retrieval.intent"]
    payload: IntentPayload


class RetrievalActionRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "action_name": "retrieval.context",
            "payload": {"query": "Where did Gerard live?", "user_id": "user-1", "k": 5, "role": "user"},
        }
    })

    action_name: Literal["retrieval.context"]
    payload: RetrievalPayload


class PromptActionRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "action_name": "retrieval.prompt",
            "payload": {
                "query": "Where did Gerard live?",
                "user_id": "user-1",
                "k": 5,
                "role": "user",
                "context_texts": ["Gerard lives in the Ooster-Waagen Straet."],
            },
        }
    })

    action_name: Literal["retrieval.prompt"]
    payload: PromptPayload
