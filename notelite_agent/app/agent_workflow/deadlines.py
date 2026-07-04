from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Callable, TypeVar

T = TypeVar("T")


class DeadlineExceeded(TimeoutError):
    """Raised when a node operation exceeds its configured deadline."""


def run_with_deadline(operation: Callable[[], T], *, timeout_seconds: float, label: str) -> T:
    if timeout_seconds <= 0:
        return operation()

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-deadline")
    future = executor.submit(operation)
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError as exc:
        future.cancel()
        raise DeadlineExceeded(f"{label} exceeded {timeout_seconds:.1f}s deadline") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
