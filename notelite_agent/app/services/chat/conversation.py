from __future__ import annotations

import logging
import time
from typing import Any

from app.services.chat.schema import ChatRequest
from app.services.ingestion.workers.celery_app import CONVERSATION_TASK, celery_app
from app.shared.backend_conversation_client import BackendConversationClient


log = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 16


def init_conversation(
    client: BackendConversationClient,
    request: ChatRequest,
    query: str,
    model: str,
    events: list[str],
    latencies_ms: dict[str, int],
) -> tuple[str, str, str]:
    """Returns (conversation_id, user_message_id, assistant_message_id).

    The assistant placeholder is created before streaming so the client gets
    a stable message_id immediately without waiting for the stream to finish.
    """
    started_at = time.perf_counter()
    conversation_id = request.conversation_id

    if not conversation_id:
        conversation = client.create_conversation(
            request.user_id, title=request.conversation_title or query[:100],
        )
        conversation_id = conversation["id"]
        events.append("conversation.created")
    else:
        events.append("conversation.reused")

    user_message = client.create_message(
        request.user_id, conversation_id, role="user", content=query,
    )
    assistant_message = client.create_message(
        request.user_id, conversation_id,
        role="assistant", content="", status="partial", model_used=model,
    )
    events.append("messages.created")
    events.extend(client.drain_events())
    latencies_ms["conversation_ms"] = int((time.perf_counter() - started_at) * 1000)
    return conversation_id, user_message["id"], assistant_message["id"]


def load_history(
    client: BackendConversationClient,
    user_id: str,
    conversation_id: str,
    exclude_message_ids: set[str],
    events: list[str],
    latencies_ms: dict[str, int],
) -> list[dict[str, str]]:
    started_at = time.perf_counter()
    history: list[dict[str, str]] = []

    for msg in client.get_messages(user_id, conversation_id):
        if msg.get("id") in exclude_message_ids:
            continue
        if msg.get("role") not in {"user", "assistant", "system"}:
            continue
        if msg.get("role") == "assistant" and msg.get("status") != "complete":
            continue
        content = (msg.get("content") or "").strip()
        if content:
            history.append({"role": msg["role"], "content": content})

    history = history[-MAX_HISTORY_MESSAGES:]
    events.append(f"history.loaded count={len(history)}")
    events.extend(client.drain_events())
    latencies_ms["history_ms"] = int((time.perf_counter() - started_at) * 1000)
    return history


def persist_assistant_message(
    *,
    request: ChatRequest,
    conversation_id: str,
    assistant_message_id: str,
    answer: str,
    model: str,
    usage: dict[str, int],
    latency_ms: int,
    error_message: str | None,
    references: list[dict[str, Any]],
    events: list[str],
    status: str | None = None,
) -> None:
    payload = {
        "user_id": request.user_id,
        "conversation_id": conversation_id,
        "message_id": assistant_message_id,
        "content": answer,
        "status": status or ("error" if error_message else "complete"),
        "model_used": model,
        "latency_ms": latency_ms,
        "tokens_used": usage.get("total_tokens"),
        "sources_used": references,
        "error_message": error_message,
    }
    try:
        celery_app.send_task(CONVERSATION_TASK, args=[payload])
        events.append("message.persist_queued")
    except Exception:
        events.append("message.persist_failed")
        log.warning("failed to queue assistant message persistence", exc_info=True)
