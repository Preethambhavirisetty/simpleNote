from typing import Generator

from fastapi import Header, HTTPException
from sqlalchemy.orm import Session

from app.core.config import AGENT_API_KEY
from app.db.postgres import DatabaseManager
from app.services.ingestion.storage.vector_store import QdrantVectorStore


def require_api_key(x_api_key: str = Header(..., alias="X-API-Key")) -> None:
    if AGENT_API_KEY and x_api_key != AGENT_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


def get_postgres_db() -> Generator[Session, None, None]:
    yield from DatabaseManager.get_session()


def get_qdrant_store() -> QdrantVectorStore:
    return QdrantVectorStore()
