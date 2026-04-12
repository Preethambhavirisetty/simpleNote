"""Ingestion orchestration — runs the pipeline and writes to vector store.

Called by Celery tasks in workers/tasks.py.  Contains the business logic
for payload validation, version guarding, and upsert/delete coordination.
"""

import logging

from core.contracts import AccessContext
from core.pg import fetch_note_version
from core.schema import IngestionTaskPayload
from core.settings import init_llama_index_settings
from pipeline import get_document_objects
from services.retrieval import VectorStore

log = logging.getLogger(__name__)


def _run_ingestion(data: dict) -> None:
    init_llama_index_settings()
    log.info("Data ingestion began for user=%s note=%s", data["user_id"], data["note_id"])
    doc_id, summary_doc, chunk_docs = get_document_objects(data)
    access_context = AccessContext(
        user_id=data["user_id"],
        role=data["role"],
        tenant_id=data.get("tenant_id"),
    )
    with VectorStore() as db:
        db.upsert(summary_doc, chunk_docs, doc_id, access_context=access_context)


def _run_delete(user_id: str, note_id: str, role: str = "user", tenant_id: str | None = None) -> None:
    access_context = AccessContext(user_id=user_id, role=role, tenant_id=tenant_id)
    with VectorStore() as db:
        db.delete_documents(
            access_context=access_context,
            filter={"user_id": user_id, "note_id": note_id},
        )


def _normalize_payload(data: dict | None = None, **kwargs) -> dict:
    """Validate and normalise raw task kwargs against IngestionTaskPayload."""
    raw: dict = {}
    if isinstance(data, dict) and data:
        raw = dict(data)
    if kwargs:
        raw.update(kwargs)
    return IngestionTaskPayload(**raw).model_dump()


def _is_stale(note_id: str, user_id: str, payload_version) -> bool:
    """Return True if the task carries an older version than what is in Postgres."""
    if payload_version is None:
        return False

    db_version = fetch_note_version(note_id, user_id)

    if db_version is None:
        log.info("note %s not found in pg for user %s — skipping upsert task", note_id, user_id)
        return True

    if int(payload_version) < db_version:
        log.info("Stale ingestion task for note %s (payload v%s < db v%s) — skipping",
                 note_id, payload_version, db_version)
        return True

    return False

# --- Main Ingestion Task ------------------------------
def run_ingestion_task(data: dict | None = None, **kwargs) -> dict:
    """Entry point for the Celery ingestion task."""
    payload = _normalize_payload(data, **kwargs)
    action = payload["action"]
    note_id = payload["note_id"]
    user_id = payload["user_id"]

    if action == "delete":
        _run_delete(
            user_id=user_id,
            note_id=note_id,
            role=payload["role"],
            tenant_id=payload["tenant_id"],
        )
        return {"message": f"delete completed for {user_id}:{note_id}", "action": "delete"}

    if _is_stale(note_id, user_id, payload["version"]):
        return {
            "message": f"skipped stale task for note {note_id}",
            "action": "skip",
            "payload_version": payload["version"],
        }

    _run_ingestion(payload)
    return {"message": f"ingestion completed for {user_id}", "action": "upsert"}
