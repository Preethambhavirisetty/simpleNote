from __future__ import annotations

from functools import lru_cache
from typing import Any

from redis import Redis, RedisError

from app.core.celery import celery_app
from app.core.config import (
    INGESTION_COALESCE_TTL_SECONDS,
    INGESTION_DEBOUNCE_SECONDS,
    INGESTION_TASK_STRING,
    MESSAGE_BROKER_URL,
)
from app.logger import get_trace_id


@lru_cache(maxsize=1)
def _redis_client() -> Redis:
    return Redis.from_url(MESSAGE_BROKER_URL, decode_responses=True)


def _pending_key(user_id: str, note_id: str) -> str:
    return f"ingest:pending:{user_id}:{note_id}"


def _send_immediate(payload: dict[str, Any], *, action: str) -> None:
    celery_app.send_task(
        INGESTION_TASK_STRING,
        kwargs={"action": action, "trace_id": get_trace_id(), **payload},
    )


def _identity(payload: dict[str, Any]) -> tuple[str, str, str | None]:
    user_id = str(payload.get("user_id") or payload.get("userid") or "").strip()
    note_id = str(payload.get("note_id") or "").strip()
    folder_id = str(payload.get("folder_id") or "").strip() or None
    return user_id, note_id, folder_id


def dispatch_upsert(payload: dict[str, Any]) -> None:
    user_id, note_id, folder_id = _identity(payload)
    if not user_id or not note_id:
        _send_immediate(payload, action="upsert")
        return

    try:
        scheduled = bool(
            _redis_client().set(
                _pending_key(user_id, note_id),
                str(payload.get("version") or ""),
                nx=True,
                ex=INGESTION_COALESCE_TTL_SECONDS,
            )
        )
    except RedisError:
        _send_immediate(payload, action="upsert")
        return

    if not scheduled:
        return

    celery_app.send_task(
        INGESTION_TASK_STRING,
        kwargs={
            "action": "upsert",
            "coalesced": True,
            "user_id": user_id,
            "userid": user_id,
            "folder_id": folder_id,
            "note_id": note_id,
            "trace_id": get_trace_id(),
        },
        countdown=INGESTION_DEBOUNCE_SECONDS,
    )


def dispatch_delete(payload: dict[str, Any]) -> None:
    user_id, note_id, _folder_id = _identity(payload)
    if user_id and note_id:
        try:
            _redis_client().delete(_pending_key(user_id, note_id))
        except RedisError:
            pass
    _send_immediate(payload, action="delete")
