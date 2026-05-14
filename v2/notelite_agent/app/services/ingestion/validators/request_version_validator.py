from sqlalchemy.orm import Session
from typing import Optional


def fetch_note_version(note_id: str, user_id: str, db: Session) -> Optional[int]:
    try:
        row = db.execute(
            "SELECT version FROM notes WHERE id = %s::uuid AND user_id = %s::uuid",
            (note_id, user_id),
        ).fetchone()
        return int(row[0]) if row is not None else None
    except Exception as exc:
        print("pg version check failed for note_id=%s user_id=%s: %s",note_id, user_id, exc)
        return None

def is_stale_ingestion(payload, db):
    user_id = payload['user_id']
    note_id = payload['note_id']

    db_version = fetch_note_version(user_id, note_id, db)

    if db_version is None:
        print("ingestion.skip", note_id=note_id, user_id=user_id, reason="note_not_found")
        return True
    if payload['version'] < db_version:
        return True
    
    return False
