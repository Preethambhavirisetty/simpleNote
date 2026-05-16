import time
from typing import Optional

from app.services.ingestion.processors.chunking.chunk_processor import ChunkProcessor
from app.services.ingestion.processors.keywords import KeywordProcessor
from app.services.ingestion.processors.summary_processor import chunk_summarizer
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

        events = ["ingestion started"]
        start = time.perf_counter()
        text = payload.get("text") or ""
        chunks = self.chunk_processor.process(text)
        chunking_end = time.perf_counter()
        events.append(f"chunking completed: {len(chunks)} chunks")

        chunks_with_kw_ent, top_kw, top_ent = self.keyword_processor.process(chunks)
        keywords_end = time.perf_counter()
        events.extend(self.keyword_processor.events)

        summary_result = chunk_summarizer(chunks)
        summary_end = time.perf_counter()
        events.extend(summary_result.events)
        events.append("ingestion completed")

        return {
            "action": action,
            "status": "processed",
            "note_id": payload.get("note_id"),
            "chunk_count": len(chunks),
            "summary": summary_result.summary,
            "api_calls": {
                "keyword_dedup": self.keyword_processor.api_calls,
                "summary": summary_result.api_calls,
                "total": self.keyword_processor.api_calls + summary_result.api_calls,
            },
            "events": events,
            "stages_ms": {
                "chunking": round((chunking_end - start) * 1000, 2),
                "keyword_extraction": round((keywords_end - chunking_end) * 1000, 2),
                "summary": round((summary_end - keywords_end) * 1000, 2),
                "total": round((summary_end - start) * 1000, 2),
            },
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
