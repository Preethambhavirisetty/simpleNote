from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.celery import celery_app
from app.core.config import INGESTION_TASK_STRING
from app.db.postgres.repos.folder import FolderRepository
from app.db.postgres.repos.note import NoteRepository
from app.exceptions.base import AppException
from app.schema.base import ErrorCode
from app.schema.folder import FolderCreate, FolderUpdate


class FolderService:
    def __init__(self):
        self.repo = FolderRepository()

    def _get_or_404(self, db: Session, folder_id: UUID, user_id: UUID):
        folder = self.repo.get_by_id(db, folder_id, user_id)
        if not folder:
            raise AppException(
                message="Folder not found",
                status_code=404,
                error_code=ErrorCode.NOT_FOUND,
            )
        return folder

    def create(self, db: Session, user_id: UUID, payload: FolderCreate):
        if self.repo.get_by_name(db, user_id, payload.name):
            raise AppException(
                message=f"A folder named '{payload.name}' already exists",
                status_code=409,
                error_code=ErrorCode.DUPLICATE_ENTRY,
            )
        folder = self.repo.create(db, user_id, payload)
        db.commit()
        db.refresh(folder)
        return folder

    def list(self, db: Session, user_id: UUID, skip: int = 0, limit: int = 50):
        return self.repo.list(db, user_id, skip=skip, limit=limit)

    def get(self, db: Session, folder_id: UUID, user_id: UUID):
        return self._get_or_404(db, folder_id, user_id)

    def update(self, db: Session, folder_id: UUID, user_id: UUID, payload: FolderUpdate):
        folder = self._get_or_404(db, folder_id, user_id)
        if payload.name and payload.name != folder.name:
            if self.repo.get_by_name(db, user_id, payload.name):
                raise AppException(
                    message=f"A folder named '{payload.name}' already exists",
                    status_code=409,
                    error_code=ErrorCode.DUPLICATE_ENTRY,
                )
        self.repo.update(db, folder, payload)
        db.commit()
        db.refresh(folder)
        return folder

    def delete(self, db: Session, folder_id: UUID, user_id: UUID, user_role: Optional[list[str]] = None):
        folder = self._get_or_404(db, folder_id, user_id)
        role = (user_role[0] if user_role else "user")

        note_repo = NoteRepository()
        child_notes = note_repo.list(db, user_id, folder_id=folder_id, limit=10000)
        del_payloads = [
            {
                "userid": str(user_id),
                "folder_id": str(folder_id),
                "note_id": str(note.id),
                "role": role,
                "tenant_id": str(user_id),
                "version": note.version,
            }
            for note in child_notes
        ]

        self.repo.delete(db, folder)
        db.commit()

        for payload in del_payloads:
            celery_app.send_task(
                INGESTION_TASK_STRING,
                kwargs={"action": "delete", **payload},
            )
