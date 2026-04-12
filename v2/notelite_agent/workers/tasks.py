"""Celery task definitions — thin wrappers that delegate to service layer."""

import logging

from workers.app import celery_app, CONVERSATION_TASK
from core.config import INGESTION_TASK_STRING
from core.settings import init_llama_index_settings
from services.ingestion import run_ingestion_task

log = logging.getLogger(__name__)

init_llama_index_settings()


@celery_app.task(
    name=INGESTION_TASK_STRING,
    acks_late=True,
    bind=True,
    autoretry_for=(ConnectionError, TimeoutError, OSError),
    max_retries=5,
    retry_backoff=True,
)
def ingest_in_background(self, data=None, **kwargs):
    return run_ingestion_task(data, **kwargs)


@celery_app.task(
    name=CONVERSATION_TASK,
    acks_late=True,
    bind=True,
    autoretry_for=(ConnectionError, TimeoutError, OSError),
    max_retries=3,
    retry_backoff=True,
)
def persist_message(self, data: dict):
    """Update the assistant message in the backend after streaming completes."""
    from services import backend_client

    backend_client.update_message(
        user_id=data["user_id"],
        conversation_id=data["conversation_id"],
        message_id=data["message_id"],
        content=data.get("content", ""),
        status=data.get("status", "complete"),
        latency_ms=data.get("latency_ms"),
        tokens_used=data.get("tokens_used"),
        sources_used=data.get("sources_used"),
        error_message=data.get("error_message"),
    )
    return {"message": f"persisted message {data['message_id']}"}
