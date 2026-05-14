from typing import Optional

from app.services.ingestion.processors.chunking.chunk_processor import ChunkProcessor
from app.services.ingestion.processors.keywords import KeywordProcessor
from app.services.ingestion.storage.vector_store import QdrantVectorStore


class IngestionOrchestrator:
    def __init__(self, vector_store: Optional[QdrantVectorStore] = None):
        self.chunk_processor = ChunkProcessor()
        self.keyword_processor = KeywordProcessor()
        self._vector_store = vector_store

    def run(self, data: Optional[dict] = None, **kwargs) -> dict:
        payload = self._payload(data, **kwargs)
        action = payload.get("action", "upsert")

        if action == "delete":
            return self.delete_action(payload)

        text = payload.get("text") or ""
        chunks = self.chunk_processor.process(text)
        keyword_result = self.keyword_processor.process(chunks)

        return {
            "action": action,
            "status": "keywords_extracted",
            "note_id": payload.get("note_id"),
            "chunk_count": len(chunks),
            "chunks": [
                {
                    "chunk_id": chunk.chunk_id,
                    "content": chunk.content,
                    "keywords": keyword_result.chunk_results[index].keywords,
                    "entities": keyword_result.chunk_results[index].entities,
                }
                for index, chunk in enumerate(chunks)
            ],
            "top_keywords": keyword_result.top_keywords,
            "entities": keyword_result.entities,
            "flattened_keywords": keyword_result.flattened_keywords,
        }

    def delete_action(self, payload: dict) -> dict:
        doc_id = self._doc_id(payload)
        self.vector_store.delete_document(doc_id)

        return {
            "action": "delete",
            "status": "deleted",
            "doc_id": doc_id,
            "note_id": payload.get("note_id"),
        }

    @staticmethod
    def _payload(data: Optional[dict], **kwargs) -> dict:
        if isinstance(data, str):
            payload = {"text": data}
        else:
            payload = dict(data or {})

        payload.update(kwargs)

        if "user_id" not in payload and "userid" in payload:
            payload["user_id"] = payload["userid"]

        return payload

    @staticmethod
    def _doc_id(payload: dict) -> str:
        doc_id = payload.get("doc_id")
        if doc_id:
            return str(doc_id)

        required_fields = ("user_id", "folder_id", "note_id")
        missing_fields = [field for field in required_fields if not payload.get(field)]
        if missing_fields:
            raise ValueError(f"Missing required delete payload fields: {', '.join(missing_fields)}")

        return f"{payload['user_id']}-{payload['folder_id']}-{payload['note_id']}"

    @property
    def vector_store(self) -> QdrantVectorStore:
        if self._vector_store is None:
            self._vector_store = QdrantVectorStore()
        return self._vector_store
