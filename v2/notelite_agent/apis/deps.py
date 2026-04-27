"""Shared FastAPI dependencies (API key auth, Postgres)."""

from collections.abc import Generator
import secrets

import psycopg
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


def get_db() -> Generator[psycopg.Connection, None, None]:
    """Yield the shared ``psycopg`` connection for the request.

    The underlying socket is process-scoped (see :mod:`core.pg`); it is not
    closed when the request ends.
    """
    from core.pg import connection as pg_connection

    yield pg_connection()

def get_qdrant():
    pass