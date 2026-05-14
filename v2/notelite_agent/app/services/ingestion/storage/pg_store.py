from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.core.config import AGENT_API_KEY, BACKEND_API_URL
from app.services.ingestion.constants import REQUEST_TIMEOUT


log = logging.getLogger(__name__)


def _headers(user_id: str) -> dict[str, str]:
    return {
        "X-Internal-Key": AGENT_API_KEY,
        "X-User-Id": user_id,
        "Content-Type": "application/json",
    }


def _url(path: str) -> str:
    return f"{BACKEND_API_URL.rstrip('/')}/api/conversations/internal{path}"


def _data(response: httpx.Response) -> Any:
    return response.json().get("data")


def get_messages(user_id: str, conversation_id: str) -> list[dict]:
    """Fetch all messages for a conversation. Returns [] on any failure."""
    try:
        resp = httpx.get(
            _url(f"/{conversation_id}"),
            headers=_headers(user_id),
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = _data(resp) or {}
        return data.get("messages", [])
    except Exception:
        log.warning("Failed to fetch backend conversation messages", exc_info=True)
        return []


def create_conversation(user_id: str, title: Optional[str] = None) -> dict:
    resp = httpx.post(
        _url("/"),
        headers=_headers(user_id),
        json={"title": title},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return _data(resp) or {}


def create_message(
    user_id: str,
    conversation_id: str,
    role: str,
    content: str = "",
    status: str = "complete",
    **kwargs,
) -> dict:
    body = {"role": role, "content": content, "status": status, **kwargs}
    resp = httpx.post(
        _url(f"/{conversation_id}/messages"),
        headers=_headers(user_id),
        json=body,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return _data(resp) or {}


def update_message(
    user_id: str,
    conversation_id: str,
    message_id: str,
    **fields,
) -> dict:
    resp = httpx.patch(
        _url(f"/{conversation_id}/messages/{message_id}"),
        headers=_headers(user_id),
        json=fields,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return _data(resp) or {}
