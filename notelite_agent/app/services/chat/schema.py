from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator


class ChatHistoryMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str = Field(..., min_length=1)


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=10_000)
    k: int = Field(5, ge=1, le=50)
    user_id: str = Field(..., min_length=1)
    role: str = Field("user")
    conversation_id: Optional[str] = Field(None, description="Existing conversation to continue")
    conversation_title: Optional[str] = Field(None, max_length=255)

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        role = v.strip().lower()
        if role not in {"user", "admin"}:
            raise ValueError("role must be 'user' or 'admin'")
        return role


class ConversationHistoryRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    conversation_id: str = Field(..., min_length=1)


class ChatCompletionRequest(BaseModel):
    """Messages for a direct non-RAG chat completion."""

    messages: list[ChatHistoryMessage] = Field(..., min_length=1)


class ChatCompletionData(BaseModel):
    response: str


class ConversationHistoryData(BaseModel):
    conversation_id: str
    messages: list[dict]
    events: list[str]
