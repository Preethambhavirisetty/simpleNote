from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.postgres.models.conversation import Conversation, Message
from app.schema.conversation import ConversationCreate, MessageCreate, MessageUpdate


class ConversationRepository:
    def get_by_id(self, db: Session, conv_id: UUID, user_id: UUID) -> Conversation | None:
        return db.execute(
            select(Conversation)
            .where(Conversation.id == conv_id, Conversation.user_id == user_id)
            .options(selectinload(Conversation.messages))
        ).scalar_one_or_none()

    def list(
        self,
        db: Session,
        user_id: UUID,
        skip: int = 0,
        limit: int = 50,
    ) -> list[Conversation]:
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(db.execute(stmt).scalars().all())

    def create(self, db: Session, user_id: UUID, data: ConversationCreate) -> Conversation:
        conv = Conversation(user_id=user_id, title=data.title)
        db.add(conv)
        return conv

    def delete(self, db: Session, conv: Conversation) -> None:
        db.delete(conv)

    def get_message(self, db: Session, msg_id: UUID, conv_id: UUID) -> Message | None:
        return db.execute(
            select(Message).where(Message.id == msg_id, Message.conversation_id == conv_id)
        ).scalar_one_or_none()

    def create_message(self, db: Session, conv_id: UUID, data: MessageCreate) -> Message:
        msg = Message(
            conversation_id=conv_id,
            role=data.role,
            content=data.content,
            status=data.status,
            model_used=data.model_used,
            latency_ms=data.latency_ms,
            tokens_used=data.tokens_used,
            sources_used=data.sources_used,
            error_message=data.error_message,
        )
        db.add(msg)
        return msg

    def update_message(self, db: Session, msg: Message, data: MessageUpdate) -> Message:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(msg, field, value)
        return msg
