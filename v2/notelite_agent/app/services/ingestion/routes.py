import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.dependencies import get_postgres_db, get_qdrant_store
from app.services.ingestion.orchestrator import IngestionOrchestrator
from app.services.ingestion.storage.vector_store import QdrantVectorStore
from app.services.ingestion.workers.celery_app import celery_app
from app.shared.schema import ApiResponse


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ingest")


@router.get("/health", response_model=ApiResponse[dict])
async def ingestion_health(
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
async def ingest_note(
    payload: dict[str, Any] = Body(...),
    vector_store: QdrantVectorStore = Depends(get_qdrant_store),
):
    """Ingest or delete a note.

    Set `action: "delete"` in the payload to remove a note's vectors.
    Otherwise the note is chunked, embedded, and upserted.
    """
    try:
        result = IngestionOrchestrator(vector_store=vector_store).run(payload)
        return ApiResponse.ok(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        # e.g. remote embedding service unreachable
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/status/{job_id}", response_model=ApiResponse[dict])
async def ingestion_job_status(job_id: str):
    """Poll the status of a background ingestion task."""
    result = celery_app.AsyncResult(job_id)
    return ApiResponse.ok({
        "job_id": job_id,
        "status": result.state,
        "result": result.result if result.ready() else None,
    })
