"""Shared FastAPI dependencies for route authentication."""

import secrets

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from core.config import AGENT_API_KEY

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(key: str | None = Security(_api_key_header)) -> None:
    """Reject requests that don't carry the correct shared secret."""
    if not key or not secrets.compare_digest(key, AGENT_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
