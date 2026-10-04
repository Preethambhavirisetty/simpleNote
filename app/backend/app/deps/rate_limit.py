from collections import OrderedDict, deque
from threading import Lock
from time import monotonic

from fastapi import Request

from app.exceptions.base import AppException
from app.schema.base import ErrorCode


class SlidingWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: int, max_keys: int = 10_000):
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._attempts: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = Lock()

    def check(self, key: str) -> None:
        now = monotonic()
        cutoff = now - self.window_seconds

        with self._lock:
            attempts = self._attempts.get(key)
            if attempts is None:
                if len(self._attempts) >= self.max_keys:
                    self._attempts.popitem(last=False)
                attempts = deque()
                self._attempts[key] = attempts
            else:
                self._attempts.move_to_end(key)

            while attempts and attempts[0] <= cutoff:
                attempts.popleft()

            if len(attempts) >= self.limit:
                raise AppException(
                    message="Too many authentication attempts. Please try again later.",
                    status_code=429,
                    error_code=ErrorCode.RATE_LIMITED,
                )

            attempts.append(now)


def client_identifier(request: Request) -> str:
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")
