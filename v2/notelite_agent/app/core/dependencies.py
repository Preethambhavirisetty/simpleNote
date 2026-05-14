from typing import Generator
from sqlalchemy.orm import Session

from app.db.postgres import DatabaseManager
from app.services.ingestion.storage.vector_store import QdrantVectorStore

def require_api_key(key):
    pass

def get_postgres_db() -> Generator[Session, None, None]:
    yield from DatabaseManager.get_session()

def get_qdrant_store() -> QdrantVectorStore:
    return QdrantVectorStore()

def get_settings():
    pass

def get_request_context():
    pass

def get_chat_service():
    pass

def get_ingestion_service():
    pass