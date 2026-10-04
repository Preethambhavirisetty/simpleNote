import json
from typing import Annotated, Any, Optional
from uuid import UUID

from pydantic import AfterValidator, BaseModel, Field

from app.core.tiptap import MAX_DOCUMENT_DEPTH

MAX_NOTE_CONTENT_BYTES = 1024 * 1024


def _validate_note_content(content: dict[str, Any]) -> dict[str, Any]:
    stack: list[tuple[Any, int]] = [(content, 1)]
    while stack:
        value, depth = stack.pop()
        if depth > MAX_DOCUMENT_DEPTH:
            raise ValueError(f"Note content exceeds maximum depth of {MAX_DOCUMENT_DEPTH}")
        if isinstance(value, dict):
            stack.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            stack.extend((child, depth + 1) for child in value)

    try:
        content_size = len(
            json.dumps(content, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
    except (RecursionError, TypeError, ValueError) as exc:
        raise ValueError("Note content must be valid JSON") from exc

    if content_size > MAX_NOTE_CONTENT_BYTES:
        raise ValueError(f"Note content must not exceed {MAX_NOTE_CONTENT_BYTES} bytes")
    return content


NoteContent = Annotated[dict[str, Any], AfterValidator(_validate_note_content)]


class NoteCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    folder_id: UUID                              # required — notes must live in a folder
    description: Optional[str] = None
    content: NoteContent = Field(default_factory=dict)
    is_pinned: bool = False
    is_memory_included: bool = False


class NoteUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    folder_id: Optional[UUID] = None
    description: Optional[str] = None
    content: Optional[NoteContent] = None
    is_pinned: Optional[bool] = None
    is_memory_included: Optional[bool] = None


class NoteMoveRequest(BaseModel):
    folder_id: UUID                              # required — must move to an existing folder
