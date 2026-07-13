from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Optional, TypeVar
from uuid import UUID

from pydantic import BaseModel, EmailStr

from app.schema.users import Role


T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Standard backend success envelope."""

    success: bool
    message: str
    data: Optional[T] = None
    error: Any | None = None


class HealthData(BaseModel):
    STATUS: str


class AuthUserData(BaseModel):
    name: str
    email: EmailStr
    role: list[Role]
    is_active: bool


class LogoutData(BaseModel):
    message: str


class UserData(BaseModel):
    id: UUID
    name: str
    email: EmailStr
    role: list[Role]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class FolderData(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    is_pinned: bool
    created_at: datetime
    updated_at: datetime


class TagData(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    created_at: datetime


class NoteTagData(BaseModel):
    id: UUID
    name: str


class NoteData(BaseModel):
    id: UUID
    user_id: UUID
    folder_id: UUID
    title: str
    description: str | None = None
    content: dict[str, Any]
    content_text: str | None = None
    is_pinned: bool
    is_memory_included: bool
    has_pii: bool = False
    tags: list[NoteTagData]
    created_at: datetime
    updated_at: datetime


class MessageData(BaseModel):
    id: UUID
    conversation_id: UUID
    role: str
    content: str
    status: str
    model_used: str | None = None
    latency_ms: int | None = None
    tokens_used: int | None = None
    sources_used: list[Any] | None = None
    error_message: str | None = None
    created_at: datetime


class ConversationData(BaseModel):
    id: UUID
    user_id: UUID
    title: str | None = None
    created_at: datetime
    updated_at: datetime


class ConversationDetailData(ConversationData):
    messages: list[MessageData]
