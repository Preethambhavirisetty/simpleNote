from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.postgres.models.note import Note
from app.db.postgres.session import get_postgres_session
from app.deps.auth import get_current_user
from app.exceptions.handlers import success_response
from app.schema.note import NoteCreate, NoteMoveRequest, NoteUpdate
from app.services.notes import NoteService


router = APIRouter(prefix="/notes", tags=["notes"])


def get_note_service():
    return NoteService()


def _note_dict(note: Note) -> dict:
    return {
        "id": str(note.id),
        "user_id": str(note.user_id),
        "folder_id": str(note.folder_id) if note.folder_id else None,
        "title": note.title,
        "content": note.content,
        "content_text": note.content_text,
        "is_pinned": note.is_pinned,
        "is_memory_included": note.is_memory_included,
        "tags": [{"id": str(t.id), "name": t.name} for t in note.tags],
        "created_at": note.created_at.isoformat(),
        "updated_at": note.updated_at.isoformat(),
    }


@router.get("/")
def list_notes(
    folder_id: Optional[UUID] = Query(None),
    pinned_only: bool = Query(False),
    search: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: NoteService = Depends(get_note_service),
):
    notes = service.list(
        db, current_user.id,
        folder_id=folder_id,
        pinned_only=pinned_only,
        search=search,
        skip=skip,
        limit=limit,
    )
    return success_response([_note_dict(n) for n in notes], "Notes retrieved")


@router.post("/")
def create_note(
    payload: NoteCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: NoteService = Depends(get_note_service),
):
    note = service.create(db, current_user.id, payload)
    return success_response(_note_dict(note), "Note created")


@router.get("/{note_id}")
def get_note(
    note_id: UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: NoteService = Depends(get_note_service),
):
    note = service.get(db, note_id, current_user.id)
    return success_response(_note_dict(note), "Note retrieved")


@router.patch("/{note_id}")
def update_note(
    note_id: UUID,
    payload: NoteUpdate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: NoteService = Depends(get_note_service),
):
    note = service.update(db, note_id, current_user.id, payload)
    return success_response(_note_dict(note), "Note updated")


@router.patch("/{note_id}/move")
def move_note(
    note_id: UUID,
    payload: NoteMoveRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: NoteService = Depends(get_note_service),
):
    note = service.move(db, note_id, current_user.id, payload)
    return success_response(_note_dict(note), "Note moved")


@router.delete("/{note_id}")
def delete_note(
    note_id: UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: NoteService = Depends(get_note_service),
):
    service.delete(db, note_id, current_user.id)
    return success_response(None, "Note deleted")


# ── Tag association ───────────────────────────────────────────────────────────

@router.post("/{note_id}/tags/{tag_id}")
def add_tag_to_note(
    note_id: UUID,
    tag_id: UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: NoteService = Depends(get_note_service),
):
    service.add_tag(db, note_id, tag_id, current_user.id)
    return success_response(None, "Tag added to note")


@router.delete("/{note_id}/tags/{tag_id}")
def remove_tag_from_note(
    note_id: UUID,
    tag_id: UUID,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_postgres_session),
    service: NoteService = Depends(get_note_service),
):
    service.remove_tag(db, note_id, tag_id, current_user.id)
    return success_response(None, "Tag removed from note")
