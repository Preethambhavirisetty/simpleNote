import logging
import uuid
from functools import lru_cache
from typing import Any

from redis import Redis, RedisError
from sqlalchemy import text
from structlog.contextvars import bind_contextvars, clear_contextvars

from app.core import crypto
from app.core.config import INGESTION_TASK_STRING, MESSAGE_BROKER_URL
from app.core.settings import init_llama_index_settings
from app.db.postgres import DatabaseManager
from app.logger import logger
from app.shared.http import TransientHTTPError, is_transient_http_error
from app.services.ingestion.orchestrator import IngestionOrchestrator
from app.services.ingestion.workers.celery_app import CONVERSATION_TASK, celery_app

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _redis_client() -> Redis:
    return Redis.from_url(MESSAGE_BROKER_URL, decode_responses=True)


def _pending_key(user_id: str, note_id: str) -> str:
    return f"ingest:pending:{user_id}:{note_id}"


def _clear_pending_marker(user_id: str, note_id: str) -> None:
    try:
        _redis_client().delete(_pending_key(user_id, note_id))
    except RedisError:
        logger.warning("ingestion.coalesce_marker_clear_failed", user_id=user_id, note_id=note_id)


def _latest_note_payload(payload: dict[str, Any]) -> dict[str, Any]:
    user_id = str(payload.get("user_id") or payload.get("userid") or "").strip()
    note_id = str(payload.get("note_id") or "").strip()
    folder_id = str(payload.get("folder_id") or "").strip()
    role = str(payload.get("role") or "user")
    if not user_id or not note_id:
        return payload

    _clear_pending_marker(user_id, note_id)

    with DatabaseManager.get_session_factory()() as session:
        row = session.execute(
            text(
                """
                SELECT n.id::text AS note_id, n.user_id::text AS user_id,
                       n.folder_id::text AS folder_id, n.title AS note_title,
                       coalesce(n.description, '') AS description,
                       coalesce(n.content_text, '') AS text, n.version AS version,
                       f.name AS folder_title,
                       (
                           SELECT coalesce(array_agg(t.name), '{}')
                           FROM notetags nt
                           JOIN tags t ON t.id = nt.tag_id
                           WHERE nt.note_id = n.id
                       ) AS tags
                FROM notes n
                JOIN folders f ON f.id = n.folder_id
                WHERE n.id::text = :note_id AND n.user_id::text = :user_id
                """
            ),
            {"note_id": note_id, "user_id": user_id},
        ).mappings().first()

    if row is None:
        return {
            "action": "delete",
            "user_id": user_id,
            "userid": user_id,
            "tenant_id": user_id,
            "folder_id": folder_id,
            "note_id": note_id,
            "role": role,
        }

    latest = dict(row)
    # Note content is encrypted at rest; decrypt what we read straight from Postgres
    # (no-op for plaintext rows) before checking emptiness or embedding it.
    for column, field in (("note_title", "note.title"), ("description", "note.description"), ("text", "note.content_text")):
        if latest.get(column) is not None:
            latest[column] = crypto.decrypt(latest[column], field)
    if not str(latest.get("text") or "").strip():
        return {
            "action": "delete",
            "user_id": user_id,
            "userid": user_id,
            "tenant_id": user_id,
            "folder_id": latest.get("folder_id") or folder_id,
            "note_id": note_id,
            "role": role,
            "version": latest.get("version"),
        }

    return {
        "action": "upsert",
        "user_id": user_id,
        "userid": user_id,
        "tenant_id": user_id,
        "folder_id": latest.get("folder_id"),
        "note_id": note_id,
        "role": role,
        "folder_title": latest.get("folder_title") or "",
        "note_title": latest.get("note_title") or "",
        "description": latest.get("description") or "",
        "tags": list(latest.get("tags") or []),
        "text": latest.get("text") or "",
        "version": latest.get("version"),
    }


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
        payload = IngestionOrchestrator._payload(data, **kwargs)
        if payload.get("coalesced"):
            payload = _latest_note_payload(payload)
        return IngestionOrchestrator().run(payload)
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
