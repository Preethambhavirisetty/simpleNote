from datetime import datetime, timezone
from typing import Any, List, Optional
from uuid import UUID as PyUUID
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.postgres.base import Base


class Note(Base):
    __tablename__ = "notes"
    __table_args__ = (
        # Most common query: list a user's notes sorted by last modified
        Index("ix_notes_user_updated", "user_id", "updated_at"),
        # Folder view: all notes inside a specific folder
        Index("ix_notes_user_folder", "user_id", "folder_id"),
        # Partial index: pinned notes — only indexes rows where is_pinned=true
        Index(
            "ix_notes_user_pinned",
            "user_id",
            postgresql_where=text("is_pinned = true"),
        ),
        # Full-text search on derived plain text (GIN for fast @@ operator)
        Index(
            "ix_notes_content_fts",
            text("to_tsvector('english', coalesce(content_text, ''))"),
            postgresql_using="gin",
        ),
    )

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # folder_id is required — every note must live inside a folder.
    # Deleting a folder cascades and deletes its notes.
    folder_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("folders.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Raw TipTap JSON document
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    # Plain text derived from content — used for full-text search and previews
    content_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(default=0)
    note_size: Mapped[int] = mapped_column(default=0)
    is_memory_included: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="notes")
    folder: Mapped["Folder"] = relationship(back_populates="notes")
    tags: Mapped[List["Tag"]] = relationship(secondary="notetags", back_populates="notes")
