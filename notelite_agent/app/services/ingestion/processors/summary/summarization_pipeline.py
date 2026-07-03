from __future__ import annotations

import time
from typing import Sequence

from app.core.config import MIN_SUMMARY_CHUNK_TOKENS
from app.services.ingestion.processors.chunking.chunk_types import ChunkType
from app.services.ingestion.processors.ingest.models import DocumentSummary, IndexChunk
from app.services.ingestion.processors.summary.questions_generator import QuestionsGenerator
from app.services.ingestion.processors.summary.summary_processor import SummaryProcessor

SUMMARY_EXCLUDED_TYPES = {ChunkType.HEADING_ONLY.value, ChunkType.CODE.value, ChunkType.JSON.value}


class SummarizationPipeline:
    """Summarize semantically enriched index chunks and generate questions."""

    def __init__(self):
        self.summary_processor = SummaryProcessor()
        self.questions_generator = QuestionsGenerator()
        self.events: list[str] = []
        self.summary_ms = 0.0
        self.questions_ms = 0.0

    def run(self, chunks: Sequence[IndexChunk]) -> DocumentSummary:
        """Produce one DocumentSummary from ordered IndexChunk input."""
        eligible = [chunk for chunk in chunks if self._include(chunk)]
        excluded = len(chunks) - len(eligible)
        summary_start = time.perf_counter()
        summary_result = self.summary_processor.process([chunk.embed_text for chunk in eligible])
        questions_start = time.perf_counter()
        questions = self.questions_generator.process(summary_result.summary)
        completed = time.perf_counter()
        self.summary_ms = round((questions_start - summary_start) * 1000, 2)
        self.questions_ms = round((completed - questions_start) * 1000, 2)
        self.events = [f"summarization pipeline started: {len(eligible)} included, {excluded} excluded"]
        self.events.extend(summary_result.events)
        self.events.extend(self.questions_generator.events)
        self.events.append("summarization pipeline completed")
        return DocumentSummary(
            summary=summary_result.summary, questions=questions,
            summary_api_calls=summary_result.api_calls,
            question_api_calls=self.questions_generator.api_calls, events=list(self.events),
        )

    @staticmethod
    def _include(chunk: IndexChunk) -> bool:
        if chunk.chunk_type in SUMMARY_EXCLUDED_TYPES or not chunk.embed_text.strip():
            return False
        if int(chunk.metadata.get("token_count") or 0) < MIN_SUMMARY_CHUNK_TOKENS:
            return False
        return "ocr" not in str(chunk.metadata.get("skip_keywords_reason") or "").lower()
