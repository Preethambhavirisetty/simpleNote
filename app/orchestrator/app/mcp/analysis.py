"""Data access for the analytical note tools.

These answer questions the ranked-retrieval tools structurally cannot. Search
returns "the best k passages"; none of these questions want a top-k list:

    "how many times did I mention the picnic"   -> a count over everything
    "what notes did I write in January 2025?"   -> a date range, not a ranking
    "when did I last write about books"         -> one date
    "did I ever mention Boston?"                -> a yes/no with evidence

Asking a top-k retriever for a count gives you k, and asking it "did I ever"
gives you its best guess whether or not anything matched. The counts and dates
here come from Postgres, which is the only place that knows about every note
rather than the most relevant few.

Two date meanings are kept apart throughout, because conflating them answers
the wrong question:

    written  - when the note was created or edited (agent_documents timestamps)
    about    - a date the note's text refers to (agent_chunk_dates, extracted
               at ingestion; "we go to Boston on March 3rd" in a note written
               in January is *about* March)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Sequence

from sqlalchemy import func, or_, select

from app.db.models import ChunkDateRecord, DocumentRecord
from app.db.postgres import DatabaseManager

DateBasis = Literal["written", "about", "either"]


def _session():
    return DatabaseManager.get_session_factory()()


def notes_written_between(
    user_id: str,
    start: datetime,
    end: datetime,
    *,
    basis: DateBasis = "written",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Documents whose write timestamps, or referenced dates, fall in a range.

    Returns document rows rather than note rows: agent_documents is what the
    index knows about, so a note missing here is a note the assistant cannot
    answer from, and saying so is more honest than listing it.
    """
    with _session() as session:
        written = or_(
            DocumentRecord.created_at.between(start, end),
            DocumentRecord.updated_at.between(start, end),
        )
        query = select(
            DocumentRecord.doc_id,
            DocumentRecord.note_id,
            DocumentRecord.folder_id,
            DocumentRecord.summary,
            DocumentRecord.created_at,
            DocumentRecord.updated_at,
        ).where(DocumentRecord.user_id == user_id)

        if basis == "written":
            query = query.where(written)
        elif basis == "about":
            query = query.where(
                DocumentRecord.doc_id.in_(
                    select(ChunkDateRecord.doc_id).where(
                        ChunkDateRecord.date_value.between(start, end)
                    )
                )
            )
        else:
            query = query.where(
                or_(
                    written,
                    DocumentRecord.doc_id.in_(
                        select(ChunkDateRecord.doc_id).where(
                            ChunkDateRecord.date_value.between(start, end)
                        )
                    ),
                )
            )

        rows = session.execute(
            query.order_by(DocumentRecord.updated_at.desc()).limit(limit)
        ).mappings().all()

    return [dict(row) for row in rows]


def referenced_dates(
    user_id: str, doc_ids: Sequence[str] | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    """Dates the note text refers to, newest first, with the phrase used."""
    with _session() as session:
        query = (
            select(
                ChunkDateRecord.doc_id,
                ChunkDateRecord.chunk_id,
                ChunkDateRecord.date_value,
                ChunkDateRecord.date_text,
                ChunkDateRecord.date_precision,
                ChunkDateRecord.date_type,
                DocumentRecord.note_id,
            )
            .join(DocumentRecord, DocumentRecord.doc_id == ChunkDateRecord.doc_id)
            .where(DocumentRecord.user_id == user_id)
        )
        if doc_ids:
            query = query.where(ChunkDateRecord.doc_id.in_(list(doc_ids)))
        rows = session.execute(
            query.order_by(ChunkDateRecord.date_value.desc()).limit(limit)
        ).mappings().all()

    return [dict(row) for row in rows]


def document_timestamps(user_id: str, doc_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    """created_at / updated_at for specific documents, keyed by doc_id."""
    if not doc_ids:
        return {}
    with _session() as session:
        rows = session.execute(
            select(
                DocumentRecord.doc_id,
                DocumentRecord.note_id,
                DocumentRecord.created_at,
                DocumentRecord.updated_at,
            ).where(
                DocumentRecord.user_id == user_id,
                DocumentRecord.doc_id.in_(list(doc_ids)),
            )
        ).mappings().all()
    return {row["doc_id"]: dict(row) for row in rows}


def indexed_note_count(user_id: str) -> int:
    """How many of the user's notes are searchable at all.

    A count of matches means nothing without this: "0 mentions" reads as "you
    never wrote about it" when the honest answer may be "nothing is indexed
    yet". Every counting tool reports both.
    """
    with _session() as session:
        return int(
            session.execute(
                select(func.count())
                .select_from(DocumentRecord)
                .where(DocumentRecord.user_id == user_id)
            ).scalar_one()
        )


def window_from_days(days: int) -> tuple[datetime, datetime]:
    end = datetime.now(timezone.utc)
    return end - timedelta(days=max(days, 1)), end


def iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else value
