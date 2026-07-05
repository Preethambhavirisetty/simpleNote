from uuid import UUID

from sqlalchemy.orm import Session

from app.db.postgres.repos.tag import TagRepository
from app.exceptions.base import AppException
from app.schema.base import ErrorCode
from app.schema.tag import TagCreate, TagUpdate


class TagService:
    def __init__(self):
        self.repo = TagRepository()

    def _get_or_404(self, db: Session, tag_id: UUID, user_id: UUID):
        tag = self.repo.get_by_id(db, tag_id, user_id)
        if not tag:
            raise AppException(
                message="Tag not found",
                status_code=404,
                error_code=ErrorCode.NOT_FOUND,
            )
        return tag

    def create(self, db: Session, user_id: UUID, payload: TagCreate):
        if self.repo.get_by_name(db, user_id, payload.name):
            raise AppException(
                message=f"Tag '{payload.name}' already exists",
                status_code=409,
                error_code=ErrorCode.DUPLICATE_ENTRY,
            )
        tag = self.repo.create(db, user_id, payload)
        db.commit()
        db.refresh(tag)
        return tag

    def list(self, db: Session, user_id: UUID):
        return self.repo.list(db, user_id)

    def get(self, db: Session, tag_id: UUID, user_id: UUID):
        return self._get_or_404(db, tag_id, user_id)

    def update(self, db: Session, tag_id: UUID, user_id: UUID, payload: TagUpdate):
        tag = self._get_or_404(db, tag_id, user_id)
        if payload.name != tag.name and self.repo.get_by_name(db, user_id, payload.name):
            raise AppException(
                message=f"Tag '{payload.name}' already exists",
                status_code=409,
                error_code=ErrorCode.DUPLICATE_ENTRY,
            )
        self.repo.update(db, tag, payload)
        db.commit()
        db.refresh(tag)
        return tag

    def delete(self, db: Session, tag_id: UUID, user_id: UUID):
        tag = self._get_or_404(db, tag_id, user_id)
        self.repo.delete(db, tag)
        db.commit()
