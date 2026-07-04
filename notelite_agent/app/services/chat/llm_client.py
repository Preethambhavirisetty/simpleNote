from __future__ import annotations

import json
import logging
from collections.abc import Iterator, Sequence
from typing import Any

import httpx

from app.core.config import LLM_API_BASE, LLM_API_KEY, LLM_REASONER_MODEL


log = logging.getLogger(__name__)

DEFAULT_MAX_TOKENS = 1024
DEFAULT_TEMPERATURE = 0.2
DEFAULT_TIMEOUT = 300.0

# Shared connection pool for LLM streaming. Streams borrow a connection and
# return it to the pool when the response context closes; timeouts per request.
_http: httpx.Client | None = None


def _http_client() -> httpx.Client:
    global _http
    if _http is None:
        _http = httpx.Client(timeout=DEFAULT_TIMEOUT)
    return _http


def stream_llm(
    messages: Sequence[dict[str, str]],
    *,
    model: str = LLM_REASONER_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = DEFAULT_TEMPERATURE,
    timeout: float = DEFAULT_TIMEOUT,
) -> Iterator[dict[str, Any]]:
    """Stream chat completions from the remote LLM (OpenAI-compatible API).

    Yields typed dicts:
        {"type": "content_delta", "content": str}
        {"type": "usage",         "usage":   dict}
        {"type": "error",         "message": str}
    """
    body = {
        "model": model,
        "messages": list(messages),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
        "stream_options": {"include_usage": True},
    }

    with _http_client().stream(
        "POST",
        _chat_completions_url(),
        headers=_headers(),
        json=body,
        timeout=timeout,
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line or not line.startswith("data:"):
                continue

            raw = line.removeprefix("data:").strip()
            if raw == "[DONE]":
                break

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                log.debug("Skipping malformed SSE line", extra={"line": raw[:200]})
                continue

            if data.get("error"):
                yield {"type": "error", "message": str(data["error"])}
                break

            usage = data.get("usage")
            if usage:
                yield {"type": "usage", "usage": usage}

            choices = data.get("choices") or []
            if not choices:
                continue

            delta = choices[0].get("delta") or {}
            content = delta.get("content")
            if content:
                yield {"type": "content_delta", "content": content}


def _chat_completions_url() -> str:
    return f"{LLM_API_BASE.rstrip('/')}/chat/completions"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }
