from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)


class MessageCreate(BaseModel):
    role: str = Field(..., pattern="^(user|assistant|system)$")
    content: str = Field("", max_length=100_000)
    status: str = Field("complete", pattern="^(partial|complete|error)$")
    model_used: Optional[str] = None
    latency_ms: Optional[int] = None
    tokens_used: Optional[int] = None
    sources_used: Optional[list] = None
    error_message: Optional[str] = None


class MessageUpdate(BaseModel):
    content: Optional[str] = Field(None, max_length=100_000)
    status: Optional[str] = Field(None, pattern="^(partial|complete|error)$")
    model_used: Optional[str] = None
    latency_ms: Optional[int] = None
    tokens_used: Optional[int] = None
    sources_used: Optional[list] = None
    error_message: Optional[str] = None
