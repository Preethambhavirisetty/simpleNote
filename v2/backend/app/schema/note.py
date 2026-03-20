from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class NoteCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    folder_id: Optional[UUID] = None
    content: dict[str, Any] = Field(default_factory=dict)
    is_pinned: bool = False
    is_memory_included: bool = False


class NoteUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    folder_id: Optional[UUID] = None
    content: Optional[dict[str, Any]] = None
    is_pinned: Optional[bool] = None
    is_memory_included: Optional[bool] = None


class NoteMoveRequest(BaseModel):
    # None moves the note to the inbox (no folder)
    folder_id: Optional[UUID] = None
