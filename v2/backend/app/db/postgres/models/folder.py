from typing import List
from datetime import datetime, timezone
from uuid import UUID as PyUUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.postgres.base import Base


class Folder(Base):
    __tablename__ = "folders"
    __table_args__ = (
        # A user cannot have two folders with the same name
        UniqueConstraint("user_id", "name", name="uq_folders_user_name"),
        # Partial index: pinned folders — same logic as notes
        Index(
            "ix_folders_user_pinned",
            "user_id",
            postgresql_where=text("is_pinned = true"),
        ),
    )

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
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

    user: Mapped["User"] = relationship(back_populates="folders")
    notes: Mapped[List["Note"]] = relationship(
        back_populates="folder", cascade="all, delete-orphan"
    )
