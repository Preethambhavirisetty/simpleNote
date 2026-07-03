from qdrant_client import QdrantClient
from app.core.config import QDRANT_URL


class QdrantClientManager:
    _client: QdrantClient | None = None

    @classmethod
    def get_client(cls) -> QdrantClient:
        if cls._client is None:
            cls._client = QdrantClient(
                url=QDRANT_URL,
            )

        return cls._client

    @classmethod
    def close(cls) -> None:
        if cls._client is not None:
            cls._client.close()
            cls._client = None