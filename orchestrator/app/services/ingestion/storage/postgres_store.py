from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, or_, select, text
from sqlalchemy.exc import ProgrammingError

from app.db.models import ChunkDateRecord, DocumentRecord, SkippedChunkRecord
from app.db.postgres import DatabaseManager
from app.services.ingestion.processors.ingest.models import IndexChunk


class PostgresArtifactStore:
    """Persist and query retrieval artifacts that do not belong in Qdrant."""

    def user_timezone(self, user_id: str) -> str:
        """Return the user's IANA timezone, falling back to UTC."""
        with DatabaseManager.get_session_factory()() as session:
            try:
                value = session.execute(
                    text("SELECT timezone FROM users WHERE id::text = :user_id"),
                    {"user_id": user_id},
                ).scalar_one_or_none()
            except Exception:
                session.rollback()
                return "UTC"
        return str(value or "UTC")

    def replace_document(
        self,
        payload: dict[str, Any],
        doc_id: str,
        chunks: Sequence[IndexChunk],
        summary: str,
        dates: Sequence[dict[str, Any]],
    ) -> None:
        """Transactionally replace all PostgreSQL retrieval artifacts for a document."""
        now = datetime.now(timezone.utc)
        created_at = payload.get("created_at") or now
        updated_at = payload.get("updated_at") or now
        timestamp_fallback = not payload.get("created_at") or not payload.get("updated_at")

        with DatabaseManager.get_session_factory().begin() as session:
            session.merge(DocumentRecord(
                doc_id=doc_id,
                user_id=str(payload["user_id"]),
                folder_id=str(payload["folder_id"]),
                note_id=str(payload["note_id"]),
                summary=summary,
                summary_generated_at=now if summary else None,
                created_at=created_at,
                updated_at=updated_at,
                timestamp_fallback=timestamp_fallback,
                # -1 when the producer sent no version (e.g. dev ingest routes);
                # such rows stay eligible for reconciliation re-ingest.
                indexed_version=int(payload.get("version") or -1),
            ))
            session.execute(delete(ChunkDateRecord).where(ChunkDateRecord.doc_id == doc_id))
            session.execute(delete(SkippedChunkRecord).where(SkippedChunkRecord.doc_id == doc_id))
            session.add_all(ChunkDateRecord(doc_id=doc_id, **date) for date in dates)
            session.add_all(self._skipped_record(doc_id, chunk) for chunk in chunks if chunk.skip_indexing)

    def delete_document(self, doc_id: str) -> None:
        with DatabaseManager.get_session_factory().begin() as session:
            session.execute(delete(DocumentRecord).where(DocumentRecord.doc_id == doc_id))

    def matching_identities(
        self,
        user_id: str | None,
        start: datetime,
        end: datetime,
    ) -> list[tuple[str, str]]:
        """Return chunk identities matching content, created, or updated dates."""
        content_conditions = [ChunkDateRecord.date_value.between(start, end)]
        document_conditions = [or_(
            DocumentRecord.created_at.between(start, end),
            DocumentRecord.updated_at.between(start, end),
        )]
        if user_id:
            content_conditions.append(DocumentRecord.user_id == user_id)
            document_conditions.append(DocumentRecord.user_id == user_id)

        try:
            with DatabaseManager.get_session_factory()() as session:
                content_rows = session.execute(
                    select(ChunkDateRecord.doc_id, ChunkDateRecord.chunk_id)
                    .join(DocumentRecord, DocumentRecord.doc_id == ChunkDateRecord.doc_id)
                    .where(*content_conditions)
                ).all()
                document_ids = session.execute(
                    select(DocumentRecord.doc_id).where(*document_conditions)
                ).scalars().all()
        except ProgrammingError as exc:
            raise self._schema_error(exc) from exc

        identities = [*(tuple(row) for row in content_rows), *((doc_id, "*") for doc_id in document_ids)]
        return list(dict.fromkeys(identities))

    def summaries(self, doc_ids: Sequence[str], limit: int) -> list[str]:
        if not doc_ids:
            return []
        try:
            with DatabaseManager.get_session_factory()() as session:
                return list(session.execute(
                    select(DocumentRecord.summary)
                    .where(DocumentRecord.doc_id.in_(doc_ids), DocumentRecord.summary != "")
                    .limit(limit)
                ).scalars())
        except ProgrammingError as exc:
            raise self._schema_error(exc) from exc

    def skipped_chunk(self, doc_id: str, chunk_id: str) -> SkippedChunkRecord | None:
        try:
            with DatabaseManager.get_session_factory()() as session:
                return session.get(SkippedChunkRecord, (doc_id, chunk_id))
        except ProgrammingError as exc:
            raise self._schema_error(exc) from exc

    @staticmethod
    def _schema_error(exc: ProgrammingError) -> RuntimeError:
        return RuntimeError(
            "Retrieval PostgreSQL schema is unavailable. Run `alembic upgrade head` "
            "from the notelite_agent directory or rebuild/restart the agent containers."
        )

    @staticmethod
    def _skipped_record(doc_id: str, chunk: IndexChunk) -> SkippedChunkRecord:
        return SkippedChunkRecord(
            doc_id=doc_id,
            chunk_id=chunk.chunk_id,
            chunk_index=chunk.chunk_index,
            chunk_type=chunk.chunk_type,
            content=chunk.content,
            embed_text=chunk.embed_text,
            prev_chunk_id=chunk.prev_chunk_id,
            next_chunk_id=chunk.next_chunk_id,
            skip_reason=chunk.skip_reason,
            metadata_json=chunk.metadata,
        )
