from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.celery import celery_app
from app.core.config import INGESTION_TASK_STRING, NOTE_SIZE_QUEUE, NOTE_SIZE_TASK_STRING
from app.core.tiptap import extract_text
from app.db.postgres.repos.folder import FolderRepository
from app.db.postgres.repos.note import NoteRepository
from app.db.postgres.repos.tag import TagRepository
from app.exceptions.base import AppException
from app.schema.base import ErrorCode
from app.schema.note import NoteCreate, NoteMoveRequest, NoteUpdate


def _dispatch_ingest(payload: dict) -> None:
    """Send an upsert ingestion task to the notelite_agent queue."""
    celery_app.send_task(
        INGESTION_TASK_STRING,
        kwargs={"action": "upsert", **payload},
    )


def _dispatch_delete(payload: dict) -> None:
    """Send a delete ingestion task to remove the vector from the store."""
    celery_app.send_task(
        INGESTION_TASK_STRING,
        kwargs={"action": "delete", **payload},
    )


def _dispatch_compute_size(note_id: UUID, content_text: str) -> None:
    """Offload note_size computation to the backend's own Celery worker."""
    celery_app.send_task(
        NOTE_SIZE_TASK_STRING,
        kwargs={"note_id": str(note_id), "content_text": content_text},
        queue=NOTE_SIZE_QUEUE,
    )


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
            "content_text": note.content_text or "",
            # The agent compares this against its own stored version to detect
            # out-of-order deliveries.
            "version": note.version,
        }

    def create(self, db: Session, user_id: UUID, payload: NoteCreate, user_role: list[str]):
        content_text = extract_text(payload.content)
        note = self.repo.create(db, user_id, payload, content_text)
        # Version 1 marks the first persisted state of the note.
        note.version = 1
        db.commit()           # commit first — note must exist before workers run
        db.refresh(note)

        if content_text:
            _dispatch_ingest(self._ingestion_payload(db, note, user_role))
            _dispatch_compute_size(note.id, content_text)
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
        content_text = extract_text(payload.content) if payload.content is not None else None
        # Bump version before the update so the committed row carries the new version
        # and any in-flight ingestion tasks with older versions are discarded by the agent.
        note.version += 1
        self.repo.update(db, note, payload, content_text)
        db.commit()
        db.refresh(note)

        if content_text:        # content changed -> re-embed + recompute size
            _dispatch_ingest(self._ingestion_payload(db, note, user_role))
            _dispatch_compute_size(note.id, content_text)
        return note

    def move(self, db: Session, note_id: UUID, user_id: UUID, payload: NoteMoveRequest):
        note = self._get_or_404(db, note_id, user_id)
        note.folder_id = payload.folder_id
        db.commit()
        db.refresh(note)
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
        _dispatch_delete(del_payload)   # remove vector after DB row is gone

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
