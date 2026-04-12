"""Ingestion endpoints — submit notes for background processing."""

import logging

from fastapi import APIRouter

from apis.schema import IngestionRequest
from workers.app import celery_app
from workers.tasks import ingest_in_background

log = logging.getLogger(__name__)

router = APIRouter(tags=["ingestion"])


@router.get("/status/{task_id}")
def get_status(task_id: str):
    result = celery_app.AsyncResult(task_id)
    inspector = celery_app.control.inspect(timeout=1.0)
    active_workers = inspector.ping() or {}
    worker_available = len(active_workers) > 0

    state = result.state
    diagnostics = None
    if state == "PENDING" and not worker_available:
        diagnostics = "No active Celery workers detected."

    return {
        "status": state,
        "result": result.result if result.ready() else None,
        "worker_available": worker_available,
        "diagnostics": diagnostics,
    }


@router.post("/ingest")
def ingest_data_to_vector_store(request: IngestionRequest):
    data = request.to_ingestion_payload()
    job = ingest_in_background.delay(data)
    return {"job_id": job.id}
