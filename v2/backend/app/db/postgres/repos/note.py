from __future__ import annotations

from uuid import UUID
from typing import Optional

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db.postgres.models.note import Note
from app.db.postgres.models.tag import NoteTags, Tag
from app.schema.note import NoteCreate, NoteUpdate


class NoteRepository:
    def get_by_id(self, db: Session, note_id: UUID, user_id: UUID) -> Note | None:
        """Fetch a single note with its tags eagerly loaded."""
        return db.execute(
            select(Note)
            .where(Note.id == note_id, Note.user_id == user_id)
            .options(selectinload(Note.tags))
        ).scalar_one_or_none()

    def list(
        self,
        db: Session,
        user_id: UUID,
        folder_id: Optional[UUID] = None,
        pinned_only: bool = False,
        search: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[Note]:
        stmt = (
            select(Note)
            .where(Note.user_id == user_id)
            .options(selectinload(Note.tags))
            .order_by(Note.is_pinned.desc(), Note.updated_at.desc())
            .offset(skip)
            .limit(limit)
        )

        if folder_id is not None:
            stmt = stmt.where(Note.folder_id == folder_id)

        if pinned_only:
            stmt = stmt.where(Note.is_pinned.is_(True))

        if search:
            stmt = stmt.where(
                or_(
                    Note.title.ilike(f"%{search}%"),
                    func.to_tsvector("english", func.coalesce(Note.content_text, "")).op("@@")(
                        func.plainto_tsquery("english", search)
                    ),
                )
            )

        return list(db.execute(stmt).scalars().all())

    def create(self, db: Session, user_id: UUID, data: NoteCreate, content_text: str) -> Note:
        note = Note(
            user_id=user_id,
            title=data.title,
            folder_id=data.folder_id,
            content=data.content,
            content_text=content_text,
            is_pinned=data.is_pinned,
            is_memory_included=data.is_memory_included,
        )
        db.add(note)
        return note

    def update(self, db: Session, note: Note, payload: NoteUpdate, content_text: Optional[str]) -> Note:
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(note, field, value)
        if content_text is not None:
            note.content_text = content_text
        return note

    def add_tag(self, db: Session, note_id: UUID, tag_id: UUID) -> None:
        db.add(NoteTags(note_id=note_id, tag_id=tag_id))

    def remove_tag(self, db: Session, note_id: UUID, tag_id: UUID) -> None:
        db.execute(
            delete(NoteTags).where(
                NoteTags.note_id == note_id, NoteTags.tag_id == tag_id
            )
        )

    def has_tag(self, db: Session, note_id: UUID, tag_id: UUID) -> bool:
        return db.execute(
            select(NoteTags).where(
                NoteTags.note_id == note_id, NoteTags.tag_id == tag_id
            )
        ).scalar_one_or_none() is not None

    def delete(self, db: Session, note: Note) -> None:
        db.delete(note)
