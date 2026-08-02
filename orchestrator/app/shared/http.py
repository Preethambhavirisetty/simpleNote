from __future__ import annotations

import httpx


class TransientHTTPError(RuntimeError):
    """Raised when an outbound HTTP failure is safe to retry."""


def is_transient_http_error(exc: BaseException) -> bool:
    if isinstance(exc, TransientHTTPError):
        return True
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        # 429 is the textbook retry case: one inference host serves ingestion,
        # chat, HyDE, and embeddings, so rate limiting under load is expected
        # operation, not a permanent failure.
        return status == 429 or 500 <= status <= 599
    return False


def retry_after_seconds(exc: BaseException, default: float = 0.0) -> float:
    """The server-requested backoff for a 429/503, or `default`.

    Only the delta-seconds form is parsed; an HTTP-date Retry-After falls back
    to the default rather than dragging in date parsing for a rare case.
    """
    if not isinstance(exc, httpx.HTTPStatusError):
        return default
    value = exc.response.headers.get("Retry-After", "")
    try:
        return max(float(value), 0.0)
    except ValueError:
        return default
