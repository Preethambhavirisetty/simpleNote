"""Internal Celery tasks for the notes domain.

These tasks run inside the *backend's own* Celery worker (not the notelite_agent).
They need DB access and use get_standalone_session() which lazily initialises the
Postgres connection on first use — so no manual init_postgres() call is needed in
the worker entry-point.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import update

from app.core.celery import celery_app
from app.db.postgres.models.note import Note
from app.db.postgres.session import get_standalone_session


@celery_app.task(
    name="notelite.tasks.notes.compute_note_size",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
)
def compute_note_size(self, note_id: str, content_text: str) -> None:
    """Compute the UTF-8 byte size of a note's plain text and persist it.

    Running this in the background keeps the HTTP response fast while still
    giving every note an accurate storage footprint without blocking the caller.

    Retry up to 3 times with exponential back-off on any transient DB error.
    """
    size = len(content_text.encode("utf-8"))

    try:
        with get_standalone_session() as db:
            db.execute(
                update(Note)
                .where(Note.id == UUID(note_id))
                .values(note_size=size)
            )
            db.commit()
    except Exception as exc:
        # Exponential back-off: 5s, 10s, 20s
        raise self.retry(exc=exc, countdown=5 * (2 ** self.request.retries)) from exc
