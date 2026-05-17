import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.dependencies import get_postgres_db, get_qdrant_store
from app.services.ingestion.orchestrator import IngestionOrchestrator
from app.services.ingestion.storage.vector_store import QdrantVectorStore
from app.services.ingestion.workers.celery_app import celery_app
from app.services.ingestion.workers.ingestion_tasks import ingest_in_background
from app.shared.schema import ApiResponse


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ingest")

_UPSERT_REQUIRED = ("user_id", "folder_id", "note_id")


def _validate_payload(payload: dict[str, Any]) -> None:
    """Raise HTTPException 400 if required fields are missing."""
    missing = [f for f in _UPSERT_REQUIRED if not payload.get(f)]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required fields: {', '.join(missing)}",
        )
    if payload.get("action", "upsert") == "upsert" and not payload.get("text", "").strip():
        raise HTTPException(status_code=400, detail="'text' is required for upsert")


@router.get("/health", response_model=ApiResponse[dict])
def ingestion_health(
    db: Session = Depends(get_postgres_db),
    vector_store: QdrantVectorStore = Depends(get_qdrant_store),
):
    """Check connectivity to PostgreSQL and Qdrant."""
    postgresql_status = "inactive"
    qdrant_status = "inactive"

    try:
        db.execute(text("select 1"))
        postgresql_status = "active"
    except Exception:
        log.warning("PostgreSQL health check failed", exc_info=True)

    try:
        vector_store.get_collections()
        qdrant_status = "active"
    except Exception:
        log.warning("Qdrant health check failed", exc_info=True)

    return ApiResponse.ok({"postgresql": postgresql_status, "qdrant": qdrant_status})


@router.post("/", response_model=ApiResponse[dict])
def ingest_note(payload: dict[str, Any] = Body(...)):
    """Queue a note for background ingestion via Celery.

    Validates required fields before queuing so bad jobs never enter the queue.
    Poll GET /api/ingest/status/{job_id} for the result.
    """
    _validate_payload(payload)
    task = ingest_in_background.delay(payload)
    return ApiResponse.ok({"job_id": task.id, "status": "queued"})


@router.post("/direct", response_model=ApiResponse[dict])
def ingest_note_direct(
    payload: dict[str, Any] = Body(...),
    vector_store: QdrantVectorStore = Depends(get_qdrant_store),
):
    """Run ingestion synchronously and return the full pipeline result.

    Development / debugging endpoint only — not for production use.
    Blocks until all LLM calls and vector writes complete (~2-5s).
    """
    _validate_payload(payload)
    try:
        result = IngestionOrchestrator(vector_store=vector_store).run(payload)
        return ApiResponse.ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/status/{job_id}", response_model=ApiResponse[dict])
def ingestion_job_status(job_id: str):
    """Poll the status of a background ingestion task."""
    result = celery_app.AsyncResult(job_id)
    return ApiResponse.ok({
        "job_id": job_id,
        "status": result.state,
        "result": result.result if result.ready() else None,
    })
