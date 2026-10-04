from __future__ import annotations

import hmac
from uuid import UUID

from app.core.config import AGENT_API_KEY
from app.exceptions.base import AppException
from app.schema.base import ErrorCode


def internal_key_matches(
    provided_key: str | None,
    *,
    expected_key: str | None = None,
) -> bool:
    configured_key = AGENT_API_KEY if expected_key is None else expected_key
    if not provided_key or not configured_key:
        return False
    return hmac.compare_digest(provided_key, configured_key)


def verify_internal_key(
    provided_key: str | None,
    *,
    expected_key: str | None = None,
) -> None:
    if not internal_key_matches(provided_key, expected_key=expected_key):
        raise AppException(
            message="Invalid credentials",
            status_code=401,
            error_code=ErrorCode.UNAUTHORIZED,
        )


def verify_internal_user_id(provided_key: str | None, user_id: str) -> UUID:
    """Authenticate an internal caller and return its validated user UUID."""
    verify_internal_key(provided_key)
    try:
        return UUID(user_id)
    except (AttributeError, TypeError, ValueError) as exc:
        raise AppException(
            message="X-User-Id must be a valid UUID",
            status_code=422,
            error_code=ErrorCode.VALIDATION_ERROR,
        ) from exc
