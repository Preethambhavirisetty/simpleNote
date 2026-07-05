from __future__ import annotations

import contextvars
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Callable, TypeVar

T = TypeVar("T")

_MAX_DEADLINE_WORKERS = max(4, int(os.getenv("AGENT_WORKFLOW_DEADLINE_WORKERS", "32")))
_EXECUTOR = ThreadPoolExecutor(max_workers=_MAX_DEADLINE_WORKERS, thread_name_prefix="agent-deadline")


class DeadlineExceeded(TimeoutError):
    """Raised when a node operation exceeds its configured deadline."""


def run_with_deadline(operation: Callable[[], T], *, timeout_seconds: float, label: str) -> T:
    if timeout_seconds <= 0:
        return operation()

    ctx = contextvars.copy_context()
    future = _EXECUTOR.submit(ctx.run, operation)
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError as exc:
        future.cancel()
        raise DeadlineExceeded(f"{label} exceeded {timeout_seconds:.1f}s deadline") from exc


def shutdown_deadline_executor() -> None:
    _EXECUTOR.shutdown(wait=False, cancel_futures=True)
