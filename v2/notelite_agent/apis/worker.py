import logging

from celery import Celery
from core.contracts import AccessContext
from core.config import (
    INGESTION_TASK_STRING,
    MESSAGE_BROKER_URL,
    CELERY_RESULT_BACKEND,
    INGESTION_QUEUE,
)
from core.pg import fetch_note_version
from core.settings import init_llama_index_settings
from services.storage_service import VectorStore
from services.chunking_service import get_document_objects

log = logging.getLogger(__name__)


worker_app = Celery(
    "tasks",
    broker=MESSAGE_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
)
worker_app.conf.update(
    result_backend=CELERY_RESULT_BACKEND,
    task_track_started=True,
    result_expires=3600,
    task_default_queue=INGESTION_QUEUE,
    task_send_sent_event=True,
    broker_connection_retry_on_startup=True,
    task_ignore_result=False,
    task_routes={INGESTION_TASK_STRING: {"queue": INGESTION_QUEUE}},
)

# Initialize once per worker process on import.
init_llama_index_settings()


def _run_ingestion(data):
    # Defensive in case worker process hot-reloads.
    init_llama_index_settings()
    doc_id, llama_docs = get_document_objects(data)
    access_context = AccessContext(
        user_id=data["user_id"],
        role=data["role"],
        tenant_id=data.get("tenant_id"),
    )
    with VectorStore() as db:
        db.upsert(
            llama_docs,
            doc_id,
            access_context=access_context,
        )


def _run_delete(user_id, note_id, role="user", tenant_id=None):
    access_context = AccessContext(
        user_id=user_id,
        role=role,
        tenant_id=tenant_id,
    )
    with VectorStore() as db:
        db.delete_documents(
            access_context=access_context,
            filter={"user_id": user_id, "note_id": note_id},
        )


def _normalize_ingestion_payload(data=None, **kwargs):
    """
    Supports both payload styles:
    1) Direct /ingest API: single `data` dict with `user_id` key.
    2) Backend Celery kwargs: note_id, userid (no underscore), content_text, action, version, ...

    Key normalisation applied here:
    - The backend dispatches `userid` (no underscore).  Rename to `user_id` so the
      rest of the pipeline (`get_document_objects`, `_run_ingestion`, etc.) can
      always rely on `data["user_id"]`.
    """
    if isinstance(data, dict) and data:
        payload = dict(data)
    else:
        payload = {}

    if kwargs:
        payload.update(kwargs)

    # Normalise backend key name → pipeline key name.
    # Done before setdefault so "userid" always wins when "user_id" is absent.
    if "user_id" not in payload and "userid" in payload:
        payload["user_id"] = payload.pop("userid")

    payload.setdefault("user_id", "UNKNOWN_USER")
    payload.setdefault("role", "user")
    payload.setdefault("tenant_id", None)
    payload.setdefault("folder_id", "BE_FOLDER_UNKNOWN")
    payload.setdefault("note_id", "BE_NOTE_UNKNOWN")
    payload.setdefault("folder_title", "Untitled Folder")
    payload.setdefault("note_title", "Untitled Note")
    payload.setdefault("description", "")
    payload.setdefault("tags", [])
    payload.setdefault("action", "upsert")
    # version is None when the task originates from the direct /ingest API endpoint
    # (no version supplied).  None means "no guard — always ingest".
    payload.setdefault("version", None)
    return payload


def _is_stale(note_id: str, user_id: str, payload_version) -> bool:
    """Return True if the task carries an older version than what is in Postgres.

    Logic:
    - If payload carries no version (None / missing) → never stale, always ingest.
    - If the note row is gone for (note_id, user_id) → skip (deleted or wrong user).
    - If payload_version < db_version → stale, skip.

    Both note_id AND user_id are used so a mis-dispatched task is rejected here
    before it can reach the vector store's AccessContext check.
    """
    if payload_version is None:
        return False

    db_version = fetch_note_version(note_id, user_id)

    if db_version is None:
        log.info(
            "note %s not found in pg for user %s — skipping upsert task",
            note_id, user_id,
        )
        return True

    if int(payload_version) < db_version:
        log.info(
            "Stale ingestion task for note %s (payload v%s < db v%s) — skipping",
            note_id, payload_version, db_version,
        )
        return True

    return False


@worker_app.task(
    name=INGESTION_TASK_STRING,
    acks_late=True,
    bind=True,
    # Only retry transient I/O failures.  Programming errors (KeyError, ValueError,
    # TypeError, PermissionError, etc.) are bugs that retrying cannot fix — let
    # them surface immediately so they are visible in monitoring.
    autoretry_for=(ConnectionError, TimeoutError, OSError),
    max_retries=5,
    retry_backoff=True,
)
def ingest_in_background(self, data=None, **kwargs):
    payload = _normalize_ingestion_payload(data, **kwargs)
    action = str(payload.get("action", "upsert")).lower()
    note_id = payload.get("note_id", "BE_NOTE_UNKNOWN")

    if action == "delete":
        # Delete is always honoured regardless of version — the note is gone.
        _run_delete(
            user_id=payload["user_id"],
            note_id=note_id,
            role=payload.get("role", "user"),
            tenant_id=payload.get("tenant_id"),
        )
        return {
            "message": f"delete completed for {payload['user_id']}:{note_id}",
            "action": "delete",
        }

    # ── Version guard ─────────────────────────────────────────────────────────
    if _is_stale(note_id, payload["user_id"], payload.get("version")):
        return {
            "message": f"skipped stale task for note {note_id}",
            "action": "skip",
            "payload_version": payload.get("version"),
        }

    _run_ingestion(payload)
    return {
        "message": f"ingestion completed for {payload['user_id']}",
        "action": "upsert",
    }