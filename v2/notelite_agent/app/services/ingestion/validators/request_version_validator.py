import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


log = logging.getLogger(__name__)


def fetch_note_version(note_id: str, user_id: str, db: Session) -> Optional[int]:
    try:
        row = db.execute(
            text("SELECT version FROM notes WHERE id = :note_id::uuid AND user_id = :user_id::uuid"),
            {"note_id": note_id, "user_id": user_id},
        ).fetchone()
        return int(row[0]) if row is not None else None
    except Exception as exc:
        log.warning("pg version check failed note_id=%s user_id=%s: %s", note_id, user_id, exc)
        return None


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
