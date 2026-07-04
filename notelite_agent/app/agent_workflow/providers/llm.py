from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
import time
from typing import Any, Protocol, TypeVar

from app.shared.http import is_transient_http_error


T = TypeVar("T")


def _with_transient_retries(operation: Callable[[], T]) -> T:
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if not is_transient_http_error(exc) or attempt == 2:
                raise
            time.sleep(0.2 * (2 ** attempt))
    raise RuntimeError("LLM request failed") from last_exc


class LlmProvider(Protocol):
    def complete(self, messages: Sequence[dict[str, Any]], *, max_tokens: int = 1024) -> str:
        ...

    def stream(self, messages: Sequence[dict[str, Any]], *, max_tokens: int = 1024) -> Iterator[str]:
        ...


class DefaultLlmProvider:
    def __init__(self, *, model: str | None = None, timeout_seconds: float | None = None):
        self.model = model
        self.timeout_seconds = timeout_seconds

    def complete(self, messages: Sequence[dict[str, Any]], *, max_tokens: int = 1024) -> str:
        from app.shared.llm import llm_call_general

        kwargs: dict[str, Any] = {"max_tokens": max_tokens}
        if self.model:
            kwargs["model"] = self.model
        if self.timeout_seconds is not None:
            kwargs["timeout"] = self.timeout_seconds
        return _with_transient_retries(lambda: llm_call_general(messages, **kwargs))

    def stream(self, messages: Sequence[dict[str, Any]], *, max_tokens: int = 1024) -> Iterator[str]:
        from app.services.chat.llm_client import stream_llm

        kwargs: dict[str, Any] = {"max_tokens": max_tokens}
        if self.model:
            kwargs["model"] = self.model
        if self.timeout_seconds is not None:
            kwargs["timeout"] = self.timeout_seconds
        for item in stream_llm(messages, **kwargs):
            item_type = item.get("type")
            if item_type == "content_delta":
                yield item.get("content") or ""
            elif item_type == "error":
                raise RuntimeError(str(item.get("message") or "LLM stream failed"))
