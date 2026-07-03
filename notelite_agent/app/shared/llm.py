from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import httpx
from llama_index.core.llms import ChatMessage

from app.core.config import LLM_API_BASE, LLM_API_KEY, LLM_SUMMARIZER_MODEL


log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 120.0
DEFAULT_MAX_TOKENS = 512
DEFAULT_TEMPERATURE = 0.1


def llm_call_direct(prompt: str) -> str:
    return llm_call_general([{"role": "user", "content": prompt}])


def llm_call_general(
    messages: Sequence[ChatMessage | dict[str, Any]],
    *,
    model: str = LLM_SUMMARIZER_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = DEFAULT_TEMPERATURE,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    body = {
        "model": model,
        "messages": [_message_to_dict(m) for m in messages],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }

    response = httpx.post(
        _chat_completions_url(),
        headers=_headers(),
        json=body,
        timeout=timeout,
    )
    response.raise_for_status()

    data = response.json()

    usage = data.get("usage") or {}
    choices = data.get("choices") or []
    finish_reason = (choices[0] or {}).get("finish_reason") if choices else None
    if usage:
        log.debug(
            "llm_usage",
            extra={
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "finish_reason": finish_reason,
            },
        )
    if finish_reason == "length":
        log.warning(
            "LLM completion reached max_tokens",
            extra={
                "model": model,
                "max_tokens": max_tokens,
                "completion_tokens": usage.get("completion_tokens"),
            },
        )

    content = _extract_message_content(data)
    if not content:
        log.warning("LLM returned empty content", extra={"response": data})
    return content


def _chat_completions_url() -> str:
    return f"{LLM_API_BASE.rstrip('/')}/chat/completions"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }


def _message_to_dict(message: ChatMessage | dict[str, Any]) -> dict[str, str]:
    if isinstance(message, ChatMessage):
        return {
            "role": getattr(message.role, "value", str(message.role)),
            "content": message.content or "",
        }
    return {
        "role": str(message["role"]),
        "content": str(message.get("content", "")),
    }


def _extract_message_content(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""

    first_choice = choices[0] or {}
    message = first_choice.get("message") or {}
    content = message.get("content")
    if content is not None:
        if isinstance(content, list):
            return "".join(str(part.get("text", part)) for part in content).strip()
        return str(content).strip()

    text = first_choice.get("text")
    if text is not None:
        return str(text).strip()

    return ""
