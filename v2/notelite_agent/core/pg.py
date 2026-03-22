"""Minimal read-only Postgres helper — version guard only.

One persistent connection per Celery worker process (Celery's prefork model
means each worker gets its own OS process, so no locking is needed).
Fails open: if the DB is unreachable the caller receives None and ingestion
proceeds normally rather than blocking the queue.
"""
from __future__ import annotations

import logging
from typing import Optional

import psycopg

from core.config import POSTGRES_DB_URL

log = logging.getLogger(__name__)

# psycopg3 uses "postgresql://..." — strip the SQLAlchemy dialect suffix if present.
# e.g. "postgresql+psycopg://user:pw@host/db" → "postgresql://user:pw@host/db"
_CONNINFO = POSTGRES_DB_URL.replace("postgresql+psycopg://", "postgresql://", 1)

_conn: Optional[psycopg.Connection] = None


def _get_conn() -> psycopg.Connection:
    """Return the cached connection, reconnecting if it has gone away."""
    global _conn
    try:
        if _conn is None or _conn.closed:
            raise RuntimeError("no connection")
        # Cheap liveness probe — raises on broken connection.
        _conn.execute("SELECT 1")
    except Exception:
        try:
            if _conn is not None and not _conn.closed:
                _conn.close()
        except Exception:
            pass
        _conn = psycopg.connect(_CONNINFO, autocommit=True)
    return _conn


def fetch_note_version(note_id: str, user_id: str) -> Optional[int]:
    """Return the `version` of the note row for the given (note_id, user_id) pair.

    Scoping by user_id means a mis-dispatched task (wrong user context) is rejected
    here — the query returns None as if the row doesn't exist, causing _is_stale to
    return True and skip ingestion without touching the vector store.

    Returns None on any DB error (fail-open: let ingestion proceed rather than
    blocking the queue on a transient DB hiccup).
    """
    try:
        row = _get_conn().execute(
            "SELECT version FROM notes WHERE id = %s::uuid AND user_id = %s::uuid",
            (note_id, user_id),
        ).fetchone()
        return int(row[0]) if row is not None else None
    except Exception as exc:
        log.warning(
            "pg version check failed for note_id=%s user_id=%s: %s",
            note_id, user_id, exc,
        )
        return None
