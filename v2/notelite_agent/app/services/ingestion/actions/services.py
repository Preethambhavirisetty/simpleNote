from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.services.ingestion.processors.chunking import ChunkProcessor, TextChunk
from app.services.ingestion.processors.ingest.document_builder import DocumentBuilder
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
            "api_calls": processor.api_calls,
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
        builder = DocumentBuilder()
        chunk_objects = [self._keyword_chunk(chunk, index) for index, chunk in enumerate(payload.chunks)]
        summary_doc, chunk_docs = builder.build(
            data=payload.model_dump(exclude={
                "chunks", "top_keywords", "entities", "questions", "note_summary"
            }),
            doc_id=self._doc_id(payload),
            chunk_objects=chunk_objects,
            top_kw=payload.top_keywords,
            top_ent=payload.entities,
            questions=payload.questions,
            note_summary=payload.note_summary,
        )
        return {
            "summary_document": self._document_payload(summary_doc) if summary_doc else None,
            "chunk_documents": [self._document_payload(doc) for doc in chunk_docs],
            "events": builder.events,
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

    @staticmethod
    def _document_payload(document: Any) -> dict[str, Any]:
        metadata = dict(document.metadata or {})
        if "content" not in metadata:
            return {
                "id": str(document.id_),
                "text": document.text,
                "metadata": metadata,
            }

        top_level_keys = (
            "chunk_id", "note_id", "folder_id", "chunk_index", "total_chunks",
            "chunk_type", "content", "embed_text", "skip_indexing", "skip_reason",
            "keywords", "entities",
        )
        artifact = {"id": str(document.id_)}
        artifact.update({key: metadata.pop(key) for key in top_level_keys})
        artifact["metadata"] = metadata
        return artifact
