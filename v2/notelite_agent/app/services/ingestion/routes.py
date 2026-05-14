import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.dependencies import get_postgres_db, get_qdrant_store
from app.services.ingestion.orchestrator import IngestionOrchestrator
from app.services.ingestion.storage.vector_store import QdrantVectorStore
from app.services.ingestion.workers.celery_app import celery_app


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ingest")


@router.get("/health")
async def ingestion_pipeline_health_check(
    db: Session=Depends(get_postgres_db),
    vector_store: QdrantVectorStore = Depends(get_qdrant_store),
):
    is_pgsql_active = "inactive"
    is_qdrant_active = "inactive"

    try:
        db.execute(text("select 1"))
        is_pgsql_active = "active"
    except Exception:
        log.warning("Failed to connect to PostgreSQL", exc_info=True)

    try:
        vector_store.get_collections()
        is_qdrant_active = "active"
    except Exception:
        log.warning("Failed to connect to Qdrant", exc_info=True)

    return {
        "routes": "active",
        "postgresql_db": is_pgsql_active,
        "qdrant_db": is_qdrant_active,
    }


@router.post("/")
async def ingest_notes(
    payload: dict[str, Any] = Body(...),
    vector_store: QdrantVectorStore = Depends(get_qdrant_store),
):
    try:
        orchestrator = IngestionOrchestrator(vector_store=vector_store)
        return orchestrator.run(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/status/{job_id}")
async def ingestion_job_status(job_id: str):
    result = celery_app.AsyncResult(job_id)
    return {
        "job_id": job_id,
        "status": result.state,
        "result": result.result if result.ready() else None,
    }
