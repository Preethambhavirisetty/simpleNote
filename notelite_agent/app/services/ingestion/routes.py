import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import ENABLE_DIRECT_INGEST
from app.core.dependencies import get_postgres_db, get_qdrant_store, require_api_key
from app.logger import logger
from app.services.ingestion.orchestrator import IngestionOrchestrator
from app.services.ingestion.schema import (
    IngestionDeletedData,
    IngestionHealthData,
    IngestionJobStatusData,
    IngestionProcessedData,
    IngestionQueuedData,
    IngestionRequest,
)
from app.services.ingestion.storage.vector_store import QdrantVectorStore
from app.services.ingestion.workers.celery_app import celery_app
from app.services.ingestion.workers.ingestion_tasks import ingest_in_background
from app.shared.schema import ApiResponse


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ingest", tags=["ingestion"], dependencies=[Depends(require_api_key)])

@router.get("/health", response_model=ApiResponse[IngestionHealthData], summary="Check ingestion dependencies")
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


@router.post("/", response_model=ApiResponse[IngestionQueuedData], summary="Queue note ingestion")
def ingest_note(payload: IngestionRequest):
    """Queue a note for background ingestion via Celery.

    Validates required fields before queuing so bad jobs never enter the queue.
    Poll GET /api/ingest/status/{job_id} for the result.
    """
    task = ingest_in_background.delay(payload.model_dump(exclude_none=True))
    return ApiResponse.ok({"job_id": task.id, "status": "queued"})


@router.post("/direct", response_model=ApiResponse[IngestionProcessedData | IngestionDeletedData], summary="Run note ingestion synchronously")
def ingest_note_direct(
    payload: IngestionRequest,
    vector_store: QdrantVectorStore = Depends(get_qdrant_store),
):
    """Run ingestion synchronously and return the full pipeline result.

    Development / debugging endpoint only — not for production use.
    Blocks until all LLM calls and vector writes complete (~2-5s).
    Disabled unless ENABLE_DIRECT_INGEST is set.
    """
    if not ENABLE_DIRECT_INGEST:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        result = IngestionOrchestrator(vector_store=vector_store).run(payload.model_dump(exclude_none=True))
        return ApiResponse.ok(result)
    except ValueError as exc:
        logger.warning("ingestion.failed", action=payload.action, note_id=payload.note_id, error_type=type(exc).__name__)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.error("ingestion.failed", action=payload.action, note_id=payload.note_id, error_type=type(exc).__name__)
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/status/{job_id}", response_model=ApiResponse[IngestionJobStatusData], summary="Get ingestion job status")
def ingestion_job_status(job_id: str):
    """Poll the status of a background ingestion task."""
    result = celery_app.AsyncResult(job_id)
    return ApiResponse.ok({
        "job_id": job_id,
        "status": result.state,
        "result": result.result if result.ready() else None,
    })
