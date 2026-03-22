from celery import Celery
from core.contracts import AccessContext
from core.config import (
    INGESTION_TASK_STRING,
    MESSAGE_BROKER_URL,
    CELERY_RESULT_BACKEND,
    INGESTION_QUEUE,
)
from core.settings import init_llama_index_settings
from services.storage_service import VectorStore
from services.chunking_service import get_document_objects


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
    1) Existing API style with single `data` dict
    2) BE celery kwargs style: note_id, user_id, content_text, action, ...
    """
    if isinstance(data, dict) and data:
        payload = dict(data)
    else:
        payload = {}

    if kwargs:
        payload.update(kwargs)

    payload.setdefault("role", "user")
    payload.setdefault("tenant_id", None)
    payload.setdefault("folder_id", "BE_FOLDER_UNKNOWN")
    payload.setdefault("note_id", "BE_NOTE_UNKNOWN")
    payload.setdefault("folder_title", "Untitled Folder")
    payload.setdefault("note_title", "Untitled Note")
    payload.setdefault("description", "")
    payload.setdefault("tags", [])
    payload.setdefault("action", "upsert")
    return payload


@worker_app.task(
    name=INGESTION_TASK_STRING,
    acks_late=True,
    bind=True,
    autoretry_for=(Exception,),
    max_retries=5,
    retry_backoff=True,
)
def ingest_in_background(self, data=None, **kwargs):
    payload = _normalize_ingestion_payload(data, **kwargs)
    action = str(payload.get("action", "upsert")).lower()

    if action == "delete":
        _run_delete(
            user_id=payload["user_id"],
            note_id=payload["note_id"],
            role=payload.get("role", "user"),
            tenant_id=payload.get("tenant_id"),
        )
        return {
            "message": f"delete completed for {payload['user_id']}:{payload['note_id']}",
            "action": "delete",
        }

    _run_ingestion(payload)
    return {
        "message": f"ingestion completed for {payload['user_id']}",
        "action": "upsert",
    }