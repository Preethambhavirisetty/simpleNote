"""Periodic Postgres<->Qdrant reconciliation.

The write path is commit-then-enqueue: a note can be committed while its
ingestion dispatch is lost (broker blip, crash between commit and enqueue) or
its indexing fails permanently. This task repairs both directions of drift:

- notes with content whose document is missing or behind (`indexed_version` <
  `notes.version`) are re-enqueued for ingestion;
- documents whose note is gone, or whose note's content is now empty, get a
  delete enqueued.

Every repair goes through the normal ingestion task, so the version guard and
idempotent replacement make reconciliation safe to run at any time — a repair
racing a newer live edit is simply skipped by the guard.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from structlog.contextvars import bind_contextvars, clear_contextvars

from app.core import crypto
from app.core.config import RECONCILE_BATCH_LIMIT
from app.db.postgres import DatabaseManager
from app.logger import logger

# Note columns encrypted at rest by the backend -> their AAD field labels for decryption.
_ENCRYPTED_NOTE_FIELDS = {
    "note_title": "note.title",
    "description": "note.description",
    "text": "note.content_text",
}


def _decrypt_note_row(row: dict[str, Any]) -> dict[str, Any]:
    """Decrypt note content read directly from Postgres (no-op for plaintext rows)."""
    for column, field in _ENCRYPTED_NOTE_FIELDS.items():
        if row.get(column) is not None:
            row[column] = crypto.decrypt(row[column], field)
    return row
from app.services.ingestion.workers.celery_app import RECONCILE_TASK, celery_app
from app.services.ingestion.workers.ingestion_tasks import ingest_in_background


_STALE_NOTES_SQL = text("""
    SELECT
        n.id::text AS note_id,
        n.user_id::text AS user_id,
        n.folder_id::text AS folder_id,
        n.title AS note_title,
        coalesce(n.description, '') AS description,
        n.content_text AS text,
        n.version AS version,
        f.name AS folder_title,
        (SELECT coalesce(array_agg(t.name), '{}')
           FROM notetags nt JOIN tags t ON t.id = nt.tag_id
          WHERE nt.note_id = n.id) AS tags
    FROM notes n
    JOIN folders f ON f.id = n.folder_id
    LEFT JOIN agent_documents d
      ON d.user_id = n.user_id::text
     AND d.note_id = n.id::text
    WHERE coalesce(n.content_text, '') <> ''
      AND (d.doc_id IS NULL OR d.indexed_version < n.version)
    ORDER BY n.updated_at
    LIMIT :limit
""")

_ORPHAN_DOCUMENTS_SQL = text("""
    SELECT d.doc_id, d.user_id, d.folder_id, d.note_id
    FROM agent_documents d
    LEFT JOIN notes n
      ON n.user_id::text = d.user_id
     AND n.id::text = d.note_id
    WHERE n.id IS NULL OR coalesce(n.content_text, '') = ''
    LIMIT :limit
""")


def find_stale_notes(session, limit: int) -> list[dict[str, Any]]:
    rows = session.execute(_STALE_NOTES_SQL, {"limit": limit}).mappings().all()
    return [_decrypt_note_row(dict(row)) for row in rows]


def find_orphan_documents(session, limit: int) -> list[dict[str, Any]]:
    rows = session.execute(_ORPHAN_DOCUMENTS_SQL, {"limit": limit}).mappings().all()
    return [dict(row) for row in rows]


def upsert_payload(row: dict[str, Any], trace_id: str) -> dict[str, Any]:
    """Same shape the backend's _dispatch_ingest sends, minus timestamps
    (celery's JSON serializer rejects datetimes; the store falls back cleanly)."""
    return {
        "action": "upsert",
        "user_id": row["user_id"],
        "folder_id": row["folder_id"],
        "note_id": row["note_id"],
        "tenant_id": row["user_id"],
        "role": "user",
        "folder_title": row["folder_title"],
        "note_title": row["note_title"],
        "description": row["description"],
        "tags": list(row["tags"] or []),
        "text": row["text"],
        "version": row["version"],
        "trace_id": trace_id,
    }


def delete_payload(row: dict[str, Any], trace_id: str) -> dict[str, Any]:
    # No `version`: the note row is gone or emptied, so the delete must proceed
    # unconditionally (the stale-delete guard only runs when version is present).
    return {
        "action": "delete",
        "user_id": row["user_id"],
        "folder_id": row["folder_id"],
        "note_id": row["note_id"],
        "tenant_id": row["user_id"],
        "role": "user",
        "trace_id": trace_id,
    }


@celery_app.task(name=RECONCILE_TASK)
def reconcile_index(limit: int | None = None) -> dict[str, int]:
    trace_id = str(uuid.uuid4())
    clear_contextvars()
    bind_contextvars(trace_id=trace_id)
    batch_limit = limit or RECONCILE_BATCH_LIMIT

    with DatabaseManager.get_session_factory()() as session:
        stale_notes = find_stale_notes(session, batch_limit)
        orphan_documents = find_orphan_documents(session, batch_limit)

    for row in stale_notes:
        ingest_in_background.delay(upsert_payload(row, trace_id))
    for row in orphan_documents:
        ingest_in_background.delay(delete_payload(row, trace_id))

    result = {"reingest_enqueued": len(stale_notes), "delete_enqueued": len(orphan_documents)}
    logger.info("reconciliation.completed", **result, batch_limit=batch_limit)
    return result
