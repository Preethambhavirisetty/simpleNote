from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tiptap import extract_text
from app.db.postgres.repos.note import NoteRepository
from app.db.postgres.repos.tag import TagRepository
from app.exceptions.base import AppException
from app.schema.base import ErrorCode
from app.schema.note import NoteCreate, NoteMoveRequest, NoteUpdate


class NoteService:
    def __init__(self):
        self.repo = NoteRepository()
        self.tag_repo = TagRepository()

    def _get_or_404(self, db: Session, note_id: UUID, user_id: UUID):
        note = self.repo.get_by_id(db, note_id, user_id)
        if not note:
            raise AppException(
                message="Note not found",
                status_code=404,
                error_code=ErrorCode.NOT_FOUND,
            )
        return note

    def create(self, db: Session, user_id: UUID, payload: NoteCreate):
        content_text = extract_text(payload.content)
        note = self.repo.create(db, user_id, payload, content_text)
        db.commit()
        db.refresh(note)
        return note

    def list(
        self,
        db: Session,
        user_id: UUID,
        folder_id: Optional[UUID] = None,
        pinned_only: bool = False,
        search: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ):
        return self.repo.list(
            db, user_id,
            folder_id=folder_id,
            pinned_only=pinned_only,
            search=search,
            skip=skip,
            limit=limit,
        )

    def get(self, db: Session, note_id: UUID, user_id: UUID):
        return self._get_or_404(db, note_id, user_id)

    def update(self, db: Session, note_id: UUID, user_id: UUID, payload: NoteUpdate):
        note = self._get_or_404(db, note_id, user_id)
        content_text = extract_text(payload.content) if payload.content is not None else None
        self.repo.update(db, note, payload, content_text)
        db.commit()
        db.refresh(note)
        return note

    def move(self, db: Session, note_id: UUID, user_id: UUID, payload: NoteMoveRequest):
        note = self._get_or_404(db, note_id, user_id)
        note.folder_id = payload.folder_id
        db.commit()
        db.refresh(note)
        return note

    def delete(self, db: Session, note_id: UUID, user_id: UUID):
        note = self._get_or_404(db, note_id, user_id)
        self.repo.delete(db, note)
        db.commit()

    # ── Tags on a note ────────────────────────────────────────────────────────

    def add_tag(self, db: Session, note_id: UUID, tag_id: UUID, user_id: UUID):
        self._get_or_404(db, note_id, user_id)
        tag = self.tag_repo.get_by_id(db, tag_id, user_id)
        if not tag:
            raise AppException(
                message="Tag not found",
                status_code=404,
                error_code=ErrorCode.NOT_FOUND,
            )
        if self.repo.has_tag(db, note_id, tag_id):
            raise AppException(
                message="Tag already added to this note",
                status_code=409,
                error_code=ErrorCode.DUPLICATE_ENTRY,
            )
        self.repo.add_tag(db, note_id, tag_id)
        db.commit()

    def remove_tag(self, db: Session, note_id: UUID, tag_id: UUID, user_id: UUID):
        self._get_or_404(db, note_id, user_id)
        if not self.repo.has_tag(db, note_id, tag_id):
            raise AppException(
                message="Tag not found on this note",
                status_code=404,
                error_code=ErrorCode.NOT_FOUND,
            )
        self.repo.remove_tag(db, note_id, tag_id)
        db.commit()
