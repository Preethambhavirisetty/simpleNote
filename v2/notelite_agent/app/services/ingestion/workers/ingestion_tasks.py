import logging

from app.core.config import INGESTION_TASK_STRING
from app.core.settings import init_llama_index_settings
from app.services.ingestion.orchestrator import IngestionOrchestrator
from app.services.ingestion.workers.celery_app import CONVERSATION_TASK, celery_app

log = logging.getLogger(__name__)


@celery_app.task(
    name=INGESTION_TASK_STRING,
    acks_late=True,
    bind=True,
    autoretry_for=(ConnectionError, TimeoutError, OSError),
    max_retries=5,
    retry_backoff=True,
)
def ingest_in_background(self, data=None, **kwargs):
    init_llama_index_settings()
    return IngestionOrchestrator().run(data, **kwargs)


@celery_app.task(
    name=CONVERSATION_TASK,
    acks_late=True,
    bind=True,
    autoretry_for=(ConnectionError, TimeoutError, OSError),
    max_retries=3,
    retry_backoff=True,
)
def persist_message(self, data: dict):
    """Update the assistant message after streaming completes or disconnects."""
    from app.shared.backend_conversation_client import BackendConversationClient
    client = BackendConversationClient()

    client.update_message(
        user_id=data["user_id"],
        conversation_id=data["conversation_id"],
        message_id=data["message_id"],
        content=data.get("content", ""),
        status=data.get("status", "complete"),
        model_used=data.get("model_used"),
        latency_ms=data.get("latency_ms"),
        tokens_used=data.get("tokens_used"),
        sources_used=data.get("sources_used"),
        error_message=data.get("error_message"),
    )
    return {"message": f"persisted message {data['message_id']}"}
