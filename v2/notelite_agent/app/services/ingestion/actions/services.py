from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.services.ingestion.processors.chunking import ChunkProcessor, TextChunk
from app.services.ingestion.processors.ingest import (
    ChunkBuilder, DocumentSummary, IndexChunk, QuestionDocument,
    SummaryArtifacts, SummaryBuilder, SummaryDocument,
)
from app.services.ingestion.processors.keywords import ChunkKeywordResult, KeywordProcessor
from app.services.ingestion.processors.summary.questions_generator import QuestionsGenerator
from app.services.ingestion.processors.summary.summarization_pipeline import SummarizationPipeline
from app.services.ingestion.storage.vector_store import QdrantVectorStore

from .schema import (
    ActionChunk, ActionIndexChunk, ActionKeywordChunk, ActionQuestionDocument,
    ActionSummaryDocument, ChunkBuildPayload, ChunkPayload, DocumentsPayload,
    IndexChunksPayload, IndexSummaryPayload, KeywordsPayload, QuestionsPayload,
    SummaryBuildPayload, SummaryPayload,
)


class IngestionActionServices:
    """Small runners for one ingestion pipeline stage at a time."""

    def __init__(self, vector_store: QdrantVectorStore | None = None):
        self.vector_store = vector_store

    def chunk(self, payload: ChunkPayload) -> dict[str, Any]:
        processor = ChunkProcessor()
        chunks = processor.process(payload.text)
        return {"chunk_count": len(chunks), "chunks": [asdict(chunk) for chunk in chunks], "events": processor.events}

    def keywords(self, payload: KeywordsPayload) -> dict[str, Any]:
        processor = KeywordProcessor()
        chunks = self._text_chunks(payload.chunks)
        chunk_results, top_keywords, entities = processor.process(chunks)
        return {
            "chunks": [asdict(chunk) for chunk in chunk_results],
            "top_keywords": top_keywords, "entities": entities,
            "api_calls": processor.api_call_counts, "events": processor.events,
        }

    def chunk_build(self, payload: ChunkBuildPayload) -> dict[str, Any]:
        data = self._identity_data(payload)
        builder = ChunkBuilder(data, self._doc_id(payload))
        chunks = builder.build([self._keyword_chunk(chunk, index) for index, chunk in enumerate(payload.chunks)])
        return {"chunks": [asdict(chunk) for chunk in chunks], "events": builder.events}

    def index_chunks(self, payload: IndexChunksPayload) -> dict[str, Any]:
        store = self._require_vector_store()
        store.replace_index_chunks(payload.document_id, self._index_chunks(payload.chunks))
        return {"events": store.events}

    def summary(self, payload: SummaryPayload) -> dict[str, Any]:
        pipeline = SummarizationPipeline()
        result = pipeline.run(self._index_chunks(payload.chunks))
        return {
            "summary": result.summary, "questions": result.questions,
            "api_calls": {"summary": result.summary_api_calls, "questions": result.question_api_calls},
            "events": result.events,
        }

    def questions(self, payload: QuestionsPayload) -> dict[str, Any]:
        generator = QuestionsGenerator()
        questions = generator.process(payload.summary)
        return {"questions": questions, "api_calls": generator.api_calls, "events": generator.events}

    def summary_build(self, payload: SummaryBuildPayload) -> dict[str, Any]:
        data = self._identity_data(payload)
        builder = SummaryBuilder(data, self._doc_id(payload), payload.top_keywords, payload.entities)
        artifacts = builder.build(DocumentSummary(summary=payload.summary, questions=payload.questions))
        return self._summary_artifacts_payload(artifacts, builder.events)

    def index_summary(self, payload: IndexSummaryPayload) -> dict[str, Any]:
        store = self._require_vector_store()
        store.events = ["summary vector ingestion started"]
        store.ensure_collections()
        store.upsert_summary_artifacts(SummaryArtifacts(
            summary=self._summary_document(payload.summary) if payload.summary else None,
            questions=[self._question_document(question) for question in payload.questions],
        ))
        store.events.append("summary vector ingestion completed")
        return {"events": store.events}

    def documents(self, payload: DocumentsPayload) -> dict[str, Any]:
        data = self._identity_data(payload)
        doc_id = self._doc_id(payload)
        chunk_builder = ChunkBuilder(data, doc_id)
        index_chunks = chunk_builder.build([self._keyword_chunk(chunk, index) for index, chunk in enumerate(payload.chunks)])
        summary_builder = SummaryBuilder(data, doc_id, payload.top_keywords, payload.entities)
        summary_artifacts = summary_builder.build(DocumentSummary(summary=payload.note_summary, questions=payload.questions))
        result = self._summary_artifacts_payload(summary_artifacts, [*chunk_builder.events, *summary_builder.events])
        result["chunks"] = [asdict(chunk) for chunk in index_chunks]
        return result

    @staticmethod
    def _text_chunks(chunks: list[ActionChunk]) -> list[TextChunk]:
        return [TextChunk(
            content=chunk.content, chunk_id=chunk.chunk_id or str(index),
            chunk_type=chunk.chunk_type, metadata=dict(chunk.metadata),
            chunk_index=chunk.chunk_index, total_chunks=chunk.total_chunks,
        ) for index, chunk in enumerate(chunks)]

    @staticmethod
    def _keyword_chunk(chunk: ActionKeywordChunk, index: int) -> ChunkKeywordResult:
        return ChunkKeywordResult(
            chunk_id=chunk.chunk_id or str(index), content=chunk.content, chunk_type=chunk.chunk_type,
            metadata=dict(chunk.metadata), keywords=chunk.keywords, entities=chunk.entities,
            chunk_index=chunk.chunk_index, total_chunks=chunk.total_chunks,
        )

    @staticmethod
    def _index_chunks(chunks: list[ActionIndexChunk]) -> list[IndexChunk]:
        return [IndexChunk(**chunk.model_dump()) for chunk in chunks]

    @staticmethod
    def _summary_document(summary: ActionSummaryDocument) -> SummaryDocument:
        return SummaryDocument(**summary.model_dump())

    @staticmethod
    def _question_document(question: ActionQuestionDocument) -> QuestionDocument:
        return QuestionDocument(**question.model_dump())

    @staticmethod
    def _identity_data(payload: Any) -> dict[str, Any]:
        return payload.model_dump(exclude={
            "chunks", "summary", "questions", "top_keywords", "entities", "note_summary"
        })

    @staticmethod
    def _summary_artifacts_payload(artifacts: SummaryArtifacts, events: list[str]) -> dict[str, Any]:
        return {
            "summary": asdict(artifacts.summary) if artifacts.summary else None,
            "questions": [asdict(question) for question in artifacts.questions],
            "events": events,
        }

    @staticmethod
    def _doc_id(payload: Any) -> str:
        return f"{payload.user_id}-{payload.folder_id}-{payload.note_id}"

    def _require_vector_store(self) -> QdrantVectorStore:
        if self.vector_store is None:
            raise RuntimeError("Qdrant vector store is required for indexing actions")
        return self.vector_store
