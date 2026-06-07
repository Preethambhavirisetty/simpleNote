from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.services.ingestion.processors.chunking import ChunkProcessor, TextChunk
from app.services.ingestion.processors.ingest import ChunkBuilder, DocumentSummary, SummaryBuilder
from app.services.ingestion.processors.keywords import ChunkKeywordResult, KeywordProcessor
from app.services.ingestion.processors.summary.questions_generator import QuestionsGenerator
from app.services.ingestion.processors.summary.summary_processor import SummaryProcessor

from .schema import (
    ActionChunk,
    ActionKeywordChunk,
    ChunkPayload,
    DocumentsPayload,
    KeywordsPayload,
    QuestionsPayload,
    SummaryPayload,
)


class IngestionActionServices:
    """Small runners for individual ingestion pipeline stages."""

    def chunk(self, payload: ChunkPayload) -> dict[str, Any]:
        processor = ChunkProcessor()
        chunks = processor.process(payload.text)
        return {
            "chunk_count": len(chunks),
            "chunks": [asdict(chunk) for chunk in chunks],
            "events": processor.events,
        }

    def keywords(self, payload: KeywordsPayload) -> dict[str, Any]:
        processor = KeywordProcessor()
        chunks = self._text_chunks(payload.chunks)
        chunk_results, top_keywords, entities = processor.process(chunks)
        return {
            "chunks": [asdict(chunk) for chunk in chunk_results],
            "top_keywords": top_keywords,
            "entities": entities,
            "api_calls": processor.api_call_counts,
            "events": processor.events,
        }

    def summary(self, payload: SummaryPayload) -> dict[str, Any]:
        processor = SummaryProcessor()
        result = processor.process(self._text_chunks(payload.chunks))
        return {
            "summary": result.summary,
            "api_calls": result.api_calls,
            "events": result.events,
        }

    def questions(self, payload: QuestionsPayload) -> dict[str, Any]:
        generator = QuestionsGenerator()
        questions = generator.process(payload.summary)
        return {
            "questions": questions,
            "api_calls": generator.api_calls,
            "events": generator.events,
        }

    def documents(self, payload: DocumentsPayload) -> dict[str, Any]:
        data = payload.model_dump(exclude={
            "chunks", "top_keywords", "entities", "questions", "note_summary"
        })
        doc_id = self._doc_id(payload)
        chunk_objects = [self._keyword_chunk(chunk, index) for index, chunk in enumerate(payload.chunks)]
        chunk_builder = ChunkBuilder(data, doc_id)
        index_chunks = chunk_builder.build(chunk_objects)
        summary_builder = SummaryBuilder(data, doc_id, payload.top_keywords, payload.entities)
        summary_artifacts = summary_builder.build(DocumentSummary(
            summary=payload.note_summary, questions=payload.questions
        ))
        return {
            "chunks": [asdict(chunk) for chunk in index_chunks],
            "summary": asdict(summary_artifacts.summary) if summary_artifacts.summary else None,
            "questions": [asdict(question) for question in summary_artifacts.questions],
            "events": [*chunk_builder.events, *summary_builder.events],
        }

    @staticmethod
    def _text_chunks(chunks: list[ActionChunk]) -> list[TextChunk]:
        return [
            TextChunk(
                content=chunk.content,
                chunk_id=chunk.chunk_id or str(index),
                chunk_type=chunk.chunk_type,
                metadata=dict(chunk.metadata),
                chunk_index=chunk.chunk_index,
                total_chunks=chunk.total_chunks,
            )
            for index, chunk in enumerate(chunks)
        ]

    @staticmethod
    def _keyword_chunk(chunk: ActionKeywordChunk, index: int) -> ChunkKeywordResult:
        return ChunkKeywordResult(
            chunk_id=chunk.chunk_id or str(index),
            content=chunk.content,
            chunk_type=chunk.chunk_type,
            metadata=dict(chunk.metadata),
            keywords=chunk.keywords,
            entities=chunk.entities,
            chunk_index=chunk.chunk_index,
            total_chunks=chunk.total_chunks,
        )

    @staticmethod
    def _doc_id(payload: DocumentsPayload) -> str:
        return f"{payload.user_id}-{payload.folder_id}-{payload.note_id}"
