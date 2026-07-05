from __future__ import annotations

import httpx


def is_transient_http_error(error: BaseException) -> bool:
    if isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout)):
        return True
    if isinstance(error, httpx.HTTPStatusError):
        return 500 <= error.response.status_code < 600
    return False
