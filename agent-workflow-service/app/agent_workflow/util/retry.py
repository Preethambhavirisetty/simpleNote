from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

from app.agent_workflow.util.http import is_transient_http_error

T = TypeVar("T")


def with_transient_retries(operation: Callable[[], T], *, max_attempts: int = 3, base_sleep_seconds: float = 0.2) -> T:
    """With transient retries."""
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if not is_transient_http_error(exc) or attempt == max_attempts - 1:
                raise
            retry_after = getattr(exc, "retry_after", None)
            sleep_seconds = retry_after if isinstance(retry_after, (int, float)) and retry_after >= 0 else base_sleep_seconds * (2**attempt)
            time.sleep(sleep_seconds)
    raise RuntimeError("Operation failed after retries") from last_exc
