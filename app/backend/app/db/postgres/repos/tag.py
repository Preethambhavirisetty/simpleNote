from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.postgres.models.tag import Tag
from app.schema.tag import TagCreate, TagUpdate


class TagRepository:
    def get_by_id(self, db: Session, tag_id: UUID, user_id: UUID) -> Tag | None:
        return db.execute(
            select(Tag).where(Tag.id == tag_id, Tag.user_id == user_id)
        ).scalar_one_or_none()

    def get_by_name(self, db: Session, user_id: UUID, name: str) -> Tag | None:
        return db.execute(
            select(Tag).where(Tag.user_id == user_id, Tag.name == name)
        ).scalar_one_or_none()

    def list(self, db: Session, user_id: UUID) -> list[Tag]:
        return list(
            db.execute(
                select(Tag).where(Tag.user_id == user_id).order_by(Tag.name)
            ).scalars().all()
        )

    def create(self, db: Session, user_id: UUID, data: TagCreate) -> Tag:
        tag = Tag(user_id=user_id, name=data.name)
        db.add(tag)
        return tag

    def update(self, db: Session, tag: Tag, payload: TagUpdate) -> Tag:
        tag.name = payload.name
        return tag

    def delete(self, db: Session, tag: Tag) -> None:
        db.delete(tag)
