from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DocumentRecord(Base):
    __tablename__ = "agent_documents"

    doc_id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(Text, index=True)
    folder_id: Mapped[str] = mapped_column(Text)
    note_id: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    summary_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timestamp_fallback: Mapped[bool] = mapped_column(default=False)
    # Note version this index state reflects; -1 = unknown (pre-tracking rows).
    # Compared against notes.version by the reconciliation task to detect drift.
    indexed_version: Mapped[int] = mapped_column(Integer, default=-1, server_default="-1")


class ChunkDateRecord(Base):
    __tablename__ = "agent_chunk_dates"

    doc_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("agent_documents.doc_id", ondelete="CASCADE"),
        primary_key=True,
    )
    chunk_id: Mapped[str] = mapped_column(Text, primary_key=True)
    date_value: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    date_text: Mapped[str] = mapped_column(Text, primary_key=True)
    date_precision: Mapped[str] = mapped_column(String(16))
    date_type: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SkippedChunkRecord(Base):
    __tablename__ = "agent_skipped_chunks"

    doc_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("agent_documents.doc_id", ondelete="CASCADE"),
        primary_key=True,
    )
    chunk_id: Mapped[str] = mapped_column(Text, primary_key=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    chunk_type: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text)
    embed_text: Mapped[str] = mapped_column(Text)
    prev_chunk_id: Mapped[str | None] = mapped_column(Text)
    next_chunk_id: Mapped[str | None] = mapped_column(Text)
    skip_reason: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
