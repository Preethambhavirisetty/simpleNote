import logging
import uuid

from structlog.contextvars import bind_contextvars, clear_contextvars

from app.core.config import INGESTION_TASK_STRING
from app.core.settings import init_llama_index_settings
from app.logger import logger
from app.shared.http import TransientHTTPError, is_transient_http_error
from app.services.ingestion.orchestrator import IngestionOrchestrator
from app.services.ingestion.workers.celery_app import CONVERSATION_TASK, celery_app

log = logging.getLogger(__name__)


def _bind_task_trace(trace_id: str | None) -> None:
    """Bind the originating request's trace id (or a fresh one) for this task.

    Cleared first: worker processes are reused across tasks, so a leftover
    context from the previous task must never leak into this one's logs.
    """
    clear_contextvars()
    bind_contextvars(trace_id=trace_id or str(uuid.uuid4()))


@celery_app.task(
    name=INGESTION_TASK_STRING,
    acks_late=True,
    bind=True,
    autoretry_for=(ConnectionError, TimeoutError, OSError),
    max_retries=5,
    retry_backoff=True,
)
def ingest_in_background(self, data=None, **kwargs):
    # trace_id rides in the payload (dict form or kwargs, depending on the
    # producer); pop it before the orchestrator sees the payload.
    trace_id = kwargs.pop("trace_id", None)
    if isinstance(data, dict):
        trace_id = data.pop("trace_id", None) or trace_id
    _bind_task_trace(trace_id)

    init_llama_index_settings()
    try:
        return IngestionOrchestrator().run(data, **kwargs)
    except Exception as exc:
        if is_transient_http_error(exc):
            raise self.retry(exc=exc) from exc
        payload = IngestionOrchestrator._payload(data, **kwargs)
        logger.exception(
            "ingestion.failed",
            action=payload.get("action", "upsert"),
            note_id=payload.get("note_id"),
        )
        raise


@celery_app.task(
    name=CONVERSATION_TASK,
    acks_late=True,
    bind=True,
    autoretry_for=(ConnectionError, TimeoutError, OSError, TransientHTTPError),
    max_retries=3,
    retry_backoff=True,
)
def persist_message(self, data: dict):
    """Update the assistant message after streaming completes or disconnects."""
    _bind_task_trace(data.pop("trace_id", None))

    from app.shared.backend_conversation_client import BackendConversationClient
    client = BackendConversationClient()

    try:
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
    except Exception as exc:
        if is_transient_http_error(exc):
            raise self.retry(exc=exc) from exc
        raise
    return {"message": f"persisted message {data['message_id']}"}
