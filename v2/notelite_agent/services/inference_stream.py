"""Stream chat completions from RunPod (OpenAI-compatible) with primary → fallback."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import httpx

from core.config import (
    LLM_API_KEY,
    get_llama_stream_model_name,
    get_stream_chat_bases,
    inference_completion_url,
)

log = logging.getLogger(__name__)


def stream_chat_completions(
    messages: list[dict],
    *,
    max_tokens: int,
    temperature: float | None,
    timeout: float,
) -> Iterator[dict[str, Any]]:
    """Yield OpenAI-style stream events from the first healthy RunPod base.

    Each yielded dict has ``type`` in ``content_delta`` | ``usage`` | ``error``.
    ``content_delta``: partial text. ``usage``: token counts when present.
    ``error``: ``{"message": str}`` then the iterator ends.
    """
    body: dict[str, Any] = {
        "model": get_llama_stream_model_name(),
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if temperature is not None:
        body["temperature"] = temperature

    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
    }

    bases = get_stream_chat_bases()
    last_error: str | None = None

    for base in bases:
        url = inference_completion_url(base)
        try:
            yield from _stream_single_base(url, body, headers, timeout)
            return
        except httpx.HTTPStatusError as e:
            last_error = f"{e.response.status_code} {e.response.text[:200]}"
            log.warning("inference_stream.http_error", base=base, error=last_error)
        except httpx.RequestError as e:
            last_error = str(e)
            log.warning("inference_stream.request_error", base=base, error=last_error)

    yield {"type": "error", "message": last_error or "All inference endpoints failed"}


def _stream_single_base(
    url: str,
    body: dict,
    headers: dict,
    timeout: float,
) -> Iterator[dict[str, Any]]:
    with httpx.Client(timeout=timeout) as client:
        with client.stream("POST", url, json=body, headers=headers) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                evt = _parse_sse_data_line(line)
                if evt is None:
                    continue
                if evt == "[DONE]":
                    return
                if isinstance(evt, dict):
                    yield from _events_from_chunk(evt)


def _parse_sse_data_line(line: str) -> dict | str | None:
    line = line.strip()
    if not line or line.startswith(":"):
        return None
    if line == "data: [DONE]":
        return "[DONE]"
    if line.startswith("data:"):
        payload = line[5:].strip()
        if payload == "[DONE]":
            return "[DONE]"
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            log.debug("inference_stream.bad_json", payload=payload[:120])
            return None
    return None


def _events_from_chunk(chunk: dict) -> Iterator[dict[str, Any]]:
    usage = chunk.get("usage")
    if usage:
        yield {"type": "usage", "usage": usage}

    choices = chunk.get("choices") or []
    if not choices:
        return
    delta = (choices[0] or {}).get("delta") or {}
    piece = delta.get("content")
    if piece:
        yield {"type": "content_delta", "content": piece}
