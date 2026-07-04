from __future__ import annotations

import httpx


class TransientHTTPError(RuntimeError):
    """Raised when an outbound HTTP failure is safe to retry."""


def is_transient_http_error(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return 500 <= exc.response.status_code <= 599
    return False
