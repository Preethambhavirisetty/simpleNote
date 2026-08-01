from typing import Generator

from fastapi import Header, HTTPException
from sqlalchemy.orm import Session

from app.core.internal_auth import verify_internal_key
from app.db.postgres import DatabaseManager
from app.services.ingestion.storage.vector_store import QdrantVectorStore


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    try:
        verify_internal_key(x_api_key)
    except HTTPException as exc:
        raise HTTPException(status_code=401, detail="Invalid API key") from exc


def get_postgres_db() -> Generator[Session, None, None]:
    yield from DatabaseManager.get_session()


def get_qdrant_store() -> QdrantVectorStore:
    return QdrantVectorStore()
