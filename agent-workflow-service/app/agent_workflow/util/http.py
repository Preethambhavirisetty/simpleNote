from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx


class WorkflowHTTPError(RuntimeError):
    """Base exception for upstream HTTP failures."""
    def __init__(self, message: str, *, status_code: int | None = None, retry_after: float | None = None):
        """Initialize this object with its runtime dependencies."""
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class TransientHTTPError(WorkflowHTTPError):
    """HTTP failure that may succeed when retried."""
    pass


class PermanentHTTPError(WorkflowHTTPError):
    """HTTP failure that should not be retried."""
    pass


def is_transient_http_error(error: BaseException) -> bool:
    """Return whether transient http error is true."""
    if isinstance(error, TransientHTTPError):
        return True
    if isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout)):
        return True
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code == 429 or 500 <= error.response.status_code < 600
    return False


def raise_for_workflow_status(response: httpx.Response, *, service: str) -> None:
    """Raise for workflow status."""
    if not response.is_error:
        return
    detail = response.text.strip()
    try:
        payload = response.json()
        if isinstance(payload, dict):
            err = payload.get("error")
            if isinstance(err, str) and err:
                detail = err
            elif isinstance(err, dict) and err.get("message"):
                detail = str(err["message"])
    except Exception:  # noqa: BLE001
        pass

    status = response.status_code
    message = f"{service} request failed ({status}): {detail or response.reason_phrase}"
    retry_after = _parse_retry_after(response.headers.get("Retry-After"))
    if status == 429 or 500 <= status < 600:
        raise TransientHTTPError(message, status_code=status, retry_after=retry_after)
    raise PermanentHTTPError(message, status_code=status)


def _parse_retry_after(value: str | None) -> float | None:
    """Parse retry after into the shape used by the workflow."""
    if not value:
        return None
    value = value.strip()
    try:
        seconds = float(value)
        return max(0.0, seconds)
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(value)
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None
    return max(0.0, retry_at.timestamp() - datetime.now(timezone.utc).timestamp())
