import time
from datetime import datetime, timezone
from typing import Optional

from app.services.ingestion.processors.chunking.chunk_processor import ChunkProcessor
from app.services.ingestion.processors.keywords import KeywordProcessor
from app.services.ingestion.processors.ingest import ChunkBuilder, SummaryBuilder
from app.services.ingestion.processors.summary.summarization_pipeline import SummarizationPipeline
from app.core.config import ACTIVE_SUMMARIZER_VERSION
from app.logger import logger
from app.services.ingestion.storage.vector_store import QdrantVectorStore
from app.shared.utils import count_tokens
from app.services.ingestion.processors.date_extractor import DateExtractor
from app.services.ingestion.storage.postgres_store import PostgresArtifactStore
from app.db.postgres import DatabaseManager
from app.services.ingestion.validators.request_version_validator import (
    fetch_note_version,
    is_stale_ingestion,
)


class IngestionOrchestrator:
    def __init__(self, vector_store: Optional[QdrantVectorStore] = None):
        self.chunk_processor = ChunkProcessor()
        self.keyword_processor = KeywordProcessor()
        self.summarization_pipeline = SummarizationPipeline()
        self._vector_store = vector_store
        self.postgres_store = PostgresArtifactStore()

    def run(self, data: Optional[dict] = None, **kwargs) -> dict:
        payload = self._payload(data, **kwargs)
        action = payload.get("action", "upsert")

        if action == "delete":
            return self.delete_action(payload)

        if self._is_stale_upsert(payload):
            return self._skipped_result(action, payload)

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
        events.extend(self.chunk_processor.events)

        # Step 2: Extract keywords and entities from chunks
        chunks_with_kw_ent, top_kw, top_ent = self.keyword_processor.process(chunks)
        keywords_end = time.perf_counter()
        events.extend(self.keyword_processor.events)

        # Step 3: Build final chunk artifacts
        chunk_builder = ChunkBuilder(payload, doc_id)
        index_chunks = chunk_builder.build(chunks_with_kw_ent)
        document_build_end = time.perf_counter()
        events.extend(chunk_builder.events)

        # Step 4: Replace and index chunk vectors before note-level summarization.
        # Re-check freshness right before writing: steps 1-3 take seconds of LLM
        # work, long enough for a newer version's task to have completed.
        if self._is_stale_upsert(payload):
            return self._skipped_result(action, payload, stage="pre_chunk_write")
        self.vector_store.replace_index_chunks(doc_id, index_chunks)
        chunk_ingestion_end = time.perf_counter()
        events.extend(self.vector_store.events)
        self.vector_store.events = []

        # Step 5: Summarize enriched chunk text and generate questions
        document_summary = self.summarization_pipeline.run(index_chunks)
        summary_end = time.perf_counter()
        events.extend(document_summary.events)

        # Step 6: Build and index summary/question artifacts. Re-check freshness
        # again: summarization is the longest stage. If stale now, the chunks
        # written in step 4 are already superseded — the newer version's own
        # replace overwrites them — so stop before writing summary artifacts.
        if self._is_stale_upsert(payload):
            return self._skipped_result(action, payload, stage="pre_summary_write")
        summary_builder = SummaryBuilder(payload, doc_id, top_kw, top_ent)
        summary_artifacts = summary_builder.build(document_summary)
        events.extend(summary_builder.events)
        summary_build_end = time.perf_counter()
        self.vector_store.upsert_summary_artifacts(summary_artifacts)
        created_at = payload.get("created_at") or datetime.now(timezone.utc)
        timezone_name = self.postgres_store.user_timezone(str(payload.get("user_id")))
        date_extractor = DateExtractor()
        dates = date_extractor.extract(index_chunks, created_at, timezone_name)
        self.postgres_store.replace_document(payload, doc_id, index_chunks, document_summary.summary, dates)
        events.extend(date_extractor.events)
        events.append("postgres retrieval artifacts replaced")
        doc_ingestion_end = time.perf_counter()
        events.extend(self.vector_store.events)

        events.append("ingestion completed")

        result = {
            "action": action,
            "status": "processed",
            "note_id": payload.get("note_id"),
            "text_tokens": text_tokens,
            "chunk_count": len(chunks),
            "top_keywords": len(top_kw),
            "entities": len(top_ent),
            "questions": document_summary.questions,
            "api_calls": {
                **self.keyword_processor.api_call_counts,
                "summary": document_summary.summary_api_calls,
                "questions": document_summary.question_api_calls,
                "total": (
                    self.keyword_processor.api_calls
                    + document_summary.summary_api_calls
                    + document_summary.question_api_calls
                ),
            },
            "events": events,
            "stages_ms": {
                "chunking": round((chunking_end - start) * 1000, 2),
                "keyword_extraction": round((keywords_end - chunking_end) * 1000, 2),
                "summary": self.summarization_pipeline.summary_ms,
                "questions": self.summarization_pipeline.questions_ms,
                "document_build": round(((document_build_end - keywords_end) + (summary_build_end - summary_end)) * 1000, 2),
                "document_ingestion": round(((chunk_ingestion_end - document_build_end) + (doc_ingestion_end - summary_build_end)) * 1000, 2),
                "total": round((doc_ingestion_end - start) * 1000, 2),
            },
            "summary": document_summary.summary
        }
        stages_ms = result["stages_ms"]
        api_calls = result["api_calls"]
        logger.info(
            "ingestion.completed",
            note_id=result["note_id"],
            summarizer_version=ACTIVE_SUMMARIZER_VERSION,
            text_tokens=text_tokens,
            chunk_count=result["chunk_count"],
            summary_skipped=not bool(document_summary.summary),
            llm_calls_total=api_calls["total"],
            keyword_extraction_calls=api_calls["keyword_extraction"],
            keyword_extraction_retries=api_calls["keyword_extraction_retries"],
            keyword_dedup_calls=api_calls["keyword_dedup"],
            entity_dedup_calls=api_calls["entity_dedup"],
            summary_calls=api_calls["summary"],
            question_calls=api_calls["questions"],
            chunking_ms=stages_ms["chunking"],
            keyword_extraction_ms=stages_ms["keyword_extraction"],
            summary_ms=stages_ms["summary"],
            questions_ms=stages_ms["questions"],
            document_build_ms=stages_ms["document_build"],
            document_ingestion_ms=stages_ms["document_ingestion"],
            total_ms=stages_ms["total"],
            events=events,
        )
        return result

    def delete_action(self, payload: dict) -> dict:
        if self._is_stale_delete(payload):
            return self._skipped_result("delete", payload)
        doc_id = self._doc_id(payload)
        self.vector_store.delete_document(doc_id)
        self.postgres_store.delete_document(doc_id)
        result = {
            "action": "delete",
            "status": "deleted",
            "doc_id": doc_id,
            "note_id": payload.get("note_id"),
        }
        logger.info("ingestion.deleted", note_id=result["note_id"])
        return result

    def _skipped_result(self, action: str, payload: dict, stage: str = "pre_pipeline") -> dict:
        logger.info(
            "ingestion.skipped",
            action=action,
            note_id=payload.get("note_id"),
            reason="stale_version",
            stage=stage,
        )
        return {
            "action": action,
            "status": "skipped",
            "note_id": payload.get("note_id"),
            "reason": "stale_version",
            "stage": stage,
        }

    def _is_stale_upsert(self, payload: dict) -> bool:
        """True when a newer note version supersedes this upsert (out-of-order/duplicate delivery)."""
        if not self._has_version_keys(payload):
            return False
        with DatabaseManager.get_session_factory()() as session:
            return is_stale_ingestion(payload, session)

    def _is_stale_delete(self, payload: dict) -> bool:
        """True only when the note still exists with a newer version.

        A missing note row is the normal case for a real delete (the backend removes the
        row before dispatching), so deletion must proceed in that case.
        """
        if not self._has_version_keys(payload):
            return False
        with DatabaseManager.get_session_factory()() as session:
            db_version = fetch_note_version(str(payload["note_id"]), str(payload["user_id"]), session)
        return db_version is not None and payload["version"] < db_version

    @staticmethod
    def _has_version_keys(payload: dict) -> bool:
        return all(payload.get(key) is not None for key in ("version", "user_id", "note_id"))

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
        # Identity is user + note only. folder_id is mutable metadata (notes move
        # between folders); including it in the id would orphan the previous
        # folder's vectors on every move. See docs/doc-id-migration.md.
        return f"{payload['user_id']}-{payload['note_id']}"

    @property
    def vector_store(self) -> QdrantVectorStore:
        if self._vector_store is None:
            self._vector_store = QdrantVectorStore()
        return self._vector_store
