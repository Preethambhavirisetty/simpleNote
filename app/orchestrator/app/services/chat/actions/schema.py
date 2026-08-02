from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.chat.schema import ChatHistoryMessage


RetrievalActionName = Literal[
    "retrieval.preprocess",
    "retrieval.hyde",
    "retrieval.embed",
    "retrieval.search",
    "retrieval.rrf",
    "retrieval.rerank",
    "retrieval.context",
    "retrieval.pipeline",
]


class RetrievalPayload(BaseModel):
    query: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1)
    k: int = Field(5, ge=1, le=50)
    role: Literal["user", "admin"] = "user"
    history: list[ChatHistoryMessage] = Field(default_factory=list)


class PromptPayload(RetrievalPayload):
    context_texts: list[str] | None = None


class StagePayload(RetrievalPayload):
    hyde_text: str | None = None
    sources: dict = Field(default_factory=dict)


class RetrievalActionRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "action_name": "retrieval.pipeline",
            "payload": {"query": "What changed?", "user_id": "user-1"},
        }
    })

    action_name: RetrievalActionName
    payload: StagePayload


class PromptActionRequest(BaseModel):
    action_name: Literal["retrieval.prompt"]
    payload: PromptPayload
