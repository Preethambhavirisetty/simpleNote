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
from core.schema import IngestionTaskPayload
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
    doc_id, summary_doc, chunk_docs = get_document_objects(data)
    access_context = AccessContext(
        user_id=data["user_id"],
        role=data["role"],
        tenant_id=data.get("tenant_id"),
    )
    with VectorStore() as db:
        db.upsert(
            summary_doc,
            chunk_docs,
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


def _normalize_ingestion_payload(data=None, **kwargs) -> dict:
    """Validate and normalise raw task kwargs against the canonical IngestionTaskPayload schema.

    Accepts two call styles:
    1) Direct /ingest HTTP API  → ``data`` is already a validated dict (user_id key).
    2) Backend Celery dispatch  → kwargs spread from the backend payload dict (userid key).

    All field-name aliasing (userid → user_id, list role → str, action lowercase) is
    handled inside IngestionTaskPayload's @model_validator.  Any unrecognised extra
    fields are silently ignored (schema Config: extra="ignore").
    """
    raw: dict = {}
    if isinstance(data, dict) and data:
        raw = dict(data)
    if kwargs:
        raw.update(kwargs)

    return IngestionTaskPayload(**raw).model_dump()


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
    action = payload["action"]          # guaranteed lowercase by schema
    note_id = payload["note_id"]
    user_id = payload["user_id"]

    if action == "delete":
        # Delete is always honoured regardless of version — the note is gone.
        _run_delete(
            user_id=user_id,
            note_id=note_id,
            role=payload["role"],
            tenant_id=payload["tenant_id"],
        )
        return {
            "message": f"delete completed for {user_id}:{note_id}",
            "action": "delete",
        }

    # ── Version guard ─────────────────────────────────────────────────────────
    if _is_stale(note_id, user_id, payload["version"]):
        return {
            "message": f"skipped stale task for note {note_id}",
            "action": "skip",
            "payload_version": payload["version"],
        }

    _run_ingestion(payload)
    return {
        "message": f"ingestion completed for {user_id}",
        "action": "upsert",
    }