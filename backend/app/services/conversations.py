from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.db.postgres.repos.conversation import ConversationRepository
from app.exceptions.base import AppException
from app.schema.base import ErrorCode
from app.schema.conversation import ConversationCreate, MessageCreate, MessageUpdate


class ConversationService:
    def __init__(self):
        self.repo = ConversationRepository()

    def _get_or_404(self, db: Session, conv_id: UUID, user_id: UUID):
        conv = self.repo.get_by_id(db, conv_id, user_id)
        if not conv:
            raise AppException(
                message="Conversation not found",
                status_code=404,
                error_code=ErrorCode.NOT_FOUND,
            )
        return conv

    def create(self, db: Session, user_id: UUID, payload: ConversationCreate):
        conv = self.repo.create(db, user_id, payload)
        db.commit()
        db.refresh(conv)
        return conv

    def list(self, db: Session, user_id: UUID, skip: int = 0, limit: int = 50):
        return self.repo.list(db, user_id, skip=skip, limit=limit)

    def get(self, db: Session, conv_id: UUID, user_id: UUID):
        return self._get_or_404(db, conv_id, user_id)

    def delete(self, db: Session, conv_id: UUID, user_id: UUID):
        conv = self._get_or_404(db, conv_id, user_id)
        self.repo.delete(db, conv)
        db.commit()

    def create_message(self, db: Session, conv_id: UUID, user_id: UUID, payload: MessageCreate):
        self._get_or_404(db, conv_id, user_id)
        msg = self.repo.create_message(db, conv_id, payload)
        db.commit()
        db.refresh(msg)
        return msg

    def update_message(
        self, db: Session, conv_id: UUID, msg_id: UUID, user_id: UUID, payload: MessageUpdate,
    ):
        self._get_or_404(db, conv_id, user_id)
        msg = self.repo.get_message(db, msg_id, conv_id)
        if not msg:
            raise AppException(
                message="Message not found",
                status_code=404,
                error_code=ErrorCode.NOT_FOUND,
            )
        self.repo.update_message(db, msg, payload)
        db.commit()
        db.refresh(msg)
        return msg
