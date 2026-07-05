from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tiptap import extract_text
from app.db.postgres.repos.folder import FolderRepository
from app.db.postgres.repos.note import NoteRepository
from app.db.postgres.repos.tag import TagRepository
from app.exceptions.base import AppException
from app.schema.base import ErrorCode
from app.schema.note import NoteCreate, NoteMoveRequest, NoteUpdate
from app.services.ingestion_dispatch import dispatch_delete, dispatch_upsert



class NoteService:
    def __init__(self):
        self.repo = NoteRepository()
        self.tag_repo = TagRepository()
        self.folder_repo = FolderRepository()

    def _get_or_404(self, db: Session, note_id: UUID, user_id: UUID):
        note = self.repo.get_by_id(db, note_id, user_id)
        if not note:
            raise AppException(
                message="Note not found",
                status_code=404,
                error_code=ErrorCode.NOT_FOUND,
            )
        return note

    def _folder_or_404(self, db: Session, folder_id: UUID, user_id: UUID):
        """Resolve a folder owned by this user; 404 hides other users' folders."""
        folder = self.folder_repo.get_by_id(db, folder_id, user_id)
        if not folder:
            raise AppException(
                message="Folder not found",
                status_code=404,
                error_code=ErrorCode.NOT_FOUND,
            )
        return folder

    def _ingestion_payload(self, db: Session, note, user_role: list[str]) -> dict:
        """Build the full payload sent to the ingestion queue.

        Includes `version` so the agent can skip stale tasks:
        if the received version < the version currently in the DB, the content
        has already been superseded and the agent should discard the task.
        """
        folder = self.folder_repo.get_by_id(db, note.folder_id, note.user_id)
        return {
            "userid": str(note.user_id),
            "folder_id": str(note.folder_id),
            "note_id": str(note.id),
            "role": user_role[0] if user_role else "user",
            # tenant_id is user_id until a multi-tenant model is introduced
            "tenant_id": str(note.user_id),
            "folder_title": folder.name if folder else "",
            "note_title": note.title,
            "description": note.description or "",
            "tags": [t.name for t in note.tags],
            "text": note.content_text or "",
            # The agent compares this against its own stored version to detect
            # out-of-order deliveries.
            "version": note.version,
        }

    def create(self, db: Session, user_id: UUID, payload: NoteCreate, user_role: list[str]):
        self._folder_or_404(db, payload.folder_id, user_id)
        content_text = extract_text(payload.content)
        note = self.repo.create(db, user_id, payload, content_text)
        # Version 1 marks the first persisted state of the note.
        note.version = 1
        note.note_size = len(content_text.encode("utf-8"))
        db.commit()           # commit first — note must exist before workers run
        db.refresh(note)

        if content_text:
            dispatch_upsert(self._ingestion_payload(db, note, user_role))
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

    def update(self, db: Session, note_id: UUID, user_id: UUID, payload: NoteUpdate, user_role: list[str]):
        note = self._get_or_404(db, note_id, user_id)
        if payload.folder_id is not None and payload.folder_id != note.folder_id:
            self._folder_or_404(db, payload.folder_id, user_id)
        content_text = extract_text(payload.content) if payload.content is not None else None
        content_changed = (
            content_text is not None and content_text != note.content_text
        )

        if content_changed:
            note.version += 1
            note.note_size = len(content_text.encode("utf-8"))

        self.repo.update(db, note, payload, content_text)
        db.commit()
        db.refresh(note)

        if content_changed:
            if content_text.strip():
                dispatch_upsert(self._ingestion_payload(db, note, user_role))
            else:
                dispatch_delete({
                    "userid": str(note.user_id),
                    "folder_id": str(note.folder_id),
                    "note_id": str(note.id),
                    "role": user_role[0] if user_role else "user",
                    "tenant_id": str(note.user_id),
                    "version": note.version,
                })
        return note

    def move(self, db: Session, note_id: UUID, user_id: UUID, payload: NoteMoveRequest, user_role: list[str]):
        note = self._get_or_404(db, note_id, user_id)
        self._folder_or_404(db, payload.folder_id, user_id)
        note.folder_id = payload.folder_id
        db.commit()
        db.refresh(note)

        # Re-index so the vector store's folder metadata reflects the new folder.
        if note.content_text and note.content_text.strip():
            dispatch_upsert(self._ingestion_payload(db, note, user_role))
        return note

    def delete(self, db: Session, note_id: UUID, user_id: UUID, user_role: list[str]):
        note = self._get_or_404(db, note_id, user_id)
        # Build payload before deleting so we still have note attributes
        del_payload = {
            "userid": str(note.user_id),
            "folder_id": str(note.folder_id),
            "note_id": str(note.id),
            "role": user_role[0] if user_role else "user",
            "tenant_id": str(note.user_id),
            "version": note.version,
        }
        self.repo.delete(db, note)
        db.commit()
        dispatch_delete(del_payload)   # remove vector after DB row is gone

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
