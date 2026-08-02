import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


log = logging.getLogger(__name__)


class NoteVersionUnavailable(RuntimeError):
    """The version query itself failed, so staleness cannot be judged."""


def fetch_note_version(note_id: str, user_id: str, db: Session) -> Optional[int]:
    """The note's current version, or None when the note does not exist.

    Casts are written as CAST(...) rather than `:note_id::uuid`: SQLAlchemy's
    bind-parameter matcher skips a `:name` that is followed by another colon,
    so the postgres cast shorthand leaves the parameter unsubstituted and the
    statement fails to parse.
    """
    try:
        row = db.execute(
            text(
                "SELECT version FROM notes "
                "WHERE id = CAST(:note_id AS uuid) AND user_id = CAST(:user_id AS uuid)"
            ),
            {"note_id": note_id, "user_id": user_id},
        ).fetchone()
    except Exception as exc:
        # A failed query is not the same as a missing note. Returning None here
        # would make every ingestion look stale and skip silently, which is how
        # a broken cast went unnoticed while the index stayed empty.
        log.exception("pg version check failed note_id=%s user_id=%s", note_id, user_id)
        raise NoteVersionUnavailable(str(exc)) from exc

    return int(row[0]) if row is not None else None


def is_stale_ingestion(payload: dict, db: Session) -> bool:
    user_id = payload["user_id"]
    note_id = payload["note_id"]

    db_version = fetch_note_version(note_id, user_id, db)

    if db_version is None:
        log.info("ingestion.skip note_id=%s user_id=%s reason=note_not_found", note_id, user_id)
        return True
    if payload["version"] < db_version:
        return True

    return False
