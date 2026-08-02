from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class NoteCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    folder_id: UUID                              # required — notes must live in a folder
    description: Optional[str] = None
    content: dict[str, Any] = Field(default_factory=dict)
    is_pinned: bool = False
    is_memory_included: bool = False


class NoteUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    folder_id: Optional[UUID] = None
    description: Optional[str] = None
    content: Optional[dict[str, Any]] = None
    is_pinned: Optional[bool] = None
    is_memory_included: Optional[bool] = None


class NoteMoveRequest(BaseModel):
    folder_id: UUID                              # required — must move to an existing folder
