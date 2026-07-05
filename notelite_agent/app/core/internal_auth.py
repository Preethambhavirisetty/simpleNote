from __future__ import annotations

import hmac

from fastapi import HTTPException

from app.core.config import AGENT_API_KEY


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
        raise HTTPException(status_code=401, detail="Invalid internal API key.")
