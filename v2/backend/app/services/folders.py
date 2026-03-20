from uuid import UUID

from sqlalchemy.orm import Session

from app.db.postgres.repos.folder import FolderRepository
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

    def delete(self, db: Session, folder_id: UUID, user_id: UUID):
        folder = self._get_or_404(db, folder_id, user_id)
        self.repo.delete(db, folder)
        db.commit()
