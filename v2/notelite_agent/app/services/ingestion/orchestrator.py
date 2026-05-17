import time
from typing import Optional

from app.services.ingestion.processors.chunking.chunk_processor import ChunkProcessor
from app.services.ingestion.processors.keywords import KeywordProcessor
from app.services.ingestion.processors.summary.questions_generator import QuestionsGenerator
from app.services.ingestion.processors.summary.summary_processor import SummaryProcessor
from app.services.ingestion.processors.ingest.document_builder import DocumentBuilder
from app.services.ingestion.storage.vector_store import QdrantVectorStore
from app.shared.utils import count_tokens


class IngestionOrchestrator:
    def __init__(self, vector_store: Optional[QdrantVectorStore] = None):
        self.chunk_processor = ChunkProcessor()
        self.keyword_processor = KeywordProcessor()
        self.summary_processor = SummaryProcessor()
        self.questions_generator = QuestionsGenerator()
        self.document_builder = DocumentBuilder()
        self._vector_store = vector_store

    def run(self, data: Optional[dict] = None, **kwargs) -> dict:
        payload = self._payload(data, **kwargs)
        action = payload.get("action", "upsert")

        if action == "delete":
            return self.delete_action(payload)

        events = ["ingestion started"]
        start = time.perf_counter()
        text = payload.get("text") or ""
        text_tokens = count_tokens(text)
        try:
            doc_id = self._doc_id(payload)
            events.append("document id created")
        except Exception as e:
            events.append(f"error creating document id: {str(e)[:20]}")
            raise

        # Step 1: Chunk the text
        chunks = self.chunk_processor.process(text)
        chunking_end = time.perf_counter()
        events.append(f"chunking completed: {len(chunks)} chunks")

        # Step 2: Extract keywords and entities from chunks
        chunks_with_kw_ent, top_kw, top_ent = self.keyword_processor.process(chunks)
        keywords_end = time.perf_counter()
        events.extend(self.keyword_processor.events)

        # Step 3: Summarize all chunks
        note_summary_obj = self.summary_processor.process(chunks)
        summary_end = time.perf_counter()
        events.extend(note_summary_obj.events)

        # Step 4: Generate questions from the summary
        questions = self.questions_generator.process(note_summary_obj.summary)
        generate_questions_end = time.perf_counter()
        events.extend(self.questions_generator.events)

        # Step 5: Build summary and chunk documents
        summary_document, chunk_documents = self.document_builder.build(
            data=payload,
            doc_id=doc_id,
            chunk_objects=chunks_with_kw_ent,
            top_kw=top_kw,
            top_ent=top_ent,
            questions=questions,
            note_summary=note_summary_obj.summary,
        )
        document_build_end = time.perf_counter()
        events.extend(self.document_builder.events)

        # Step 6: Upsert into vector store
        self.vector_store.replace_document(
            doc_id,
            summary=summary_document,
            chunks=chunk_documents,
        )
        doc_ingestion_end = time.perf_counter()
        events.extend(self.vector_store.events)

        events.append("ingestion completed")

        return {
            "action": action,
            "status": "processed",
            "note_id": payload.get("note_id"),
            "text_tokens": text_tokens,
            "chunk_count": len(chunks),
            "top_keywords": top_kw,
            "entities": top_ent,
            "summary": note_summary_obj.summary,
            "questions": questions,
            "api_calls": {
                "keyword_dedup": self.keyword_processor.api_calls,
                "summary": note_summary_obj.api_calls,
                "questions": self.questions_generator.api_calls,
                "total": (
                    self.keyword_processor.api_calls
                    + note_summary_obj.api_calls
                    + self.questions_generator.api_calls
                ),
            },
            "events": events,
            "stages_ms": {
                "chunking": round((chunking_end - start) * 1000, 2),
                "keyword_extraction": round((keywords_end - chunking_end) * 1000, 2),
                "summary": round((summary_end - keywords_end) * 1000, 2),
                "questions": round((generate_questions_end - summary_end) * 1000, 2),
                "document_build": round((document_build_end - generate_questions_end) * 1000, 2),
                "document_ingestion": round((doc_ingestion_end - document_build_end) * 1000, 2),
                "total": round((doc_ingestion_end - start) * 1000, 2),
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
        payload = {"text": data} if isinstance(data, str) else dict(data or {})
        payload.update(kwargs)
        if "user_id" not in payload and "userid" in payload:
            payload["user_id"] = payload["userid"]
        return payload

    @staticmethod
    def _doc_id(payload: dict) -> str:
        required_fields = ("user_id", "folder_id", "note_id")
        missing = [f for f in required_fields if not payload.get(f)]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")
        return f"{payload['user_id']}-{payload['folder_id']}-{payload['note_id']}"

    @property
    def vector_store(self) -> QdrantVectorStore:
        if self._vector_store is None:
            self._vector_store = QdrantVectorStore()
        return self._vector_store
