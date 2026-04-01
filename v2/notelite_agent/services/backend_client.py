"""Thin HTTP client for the notelite backend's internal conversation API."""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from core.config import AGENT_API_KEY, BACKEND_API_URL

log = logging.getLogger(__name__)

_TIMEOUT = 10.0


def _headers(user_id: str) -> dict:
    return {
        "X-Internal-Key": AGENT_API_KEY,
        "X-User-Id": user_id,
        "Content-Type": "application/json",
    }


def _url(path: str) -> str:
    return f"{BACKEND_API_URL.rstrip('/')}/api/conversations/internal{path}"


def create_conversation(user_id: str, title: Optional[str] = None) -> dict:
    resp = httpx.post(
        _url("/"),
        headers=_headers(user_id),
        json={"title": title},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["data"]


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
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["data"]


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
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["data"]
