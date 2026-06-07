from __future__ import annotations

import hashlib
from typing import Any, Sequence

from app.services.ingestion.processors.ingest.models import (
    DocumentSummary, QuestionDocument, SummaryArtifacts, SummaryDocument,
)


class SummaryBuilder:
    """Build vendor-neutral summary and question artifacts."""

    def __init__(
        self, data: dict[str, Any], document_id: str,
        keywords: Sequence[str] = (), entities: Sequence[str] = (),
    ):
        self.data = data
        self.document_id = document_id
        self.keywords = list(keywords)
        self.entities = list(entities)
        self.events: list[str] = []

    def build(self, result: DocumentSummary) -> SummaryArtifacts:
        """Convert one DocumentSummary input into summary and question artifacts."""
        self.events = ["summary artifacts build started"]
        metadata = self._metadata()
        summary = None
        if result.summary.strip():
            summary = SummaryDocument(
                document_id=self.document_id,
                summary_id=self._id("summary"),
                content=result.summary.strip(),
                embed_text=result.summary.strip(),
                keywords=self.keywords,
                entities=self.entities,
                metadata=metadata,
            )
        questions = [
            QuestionDocument(
                document_id=self.document_id,
                question_id=self._id(f"question-{index}"),
                content=question.strip(),
                embed_text=question.strip(),
                metadata=metadata,
            )
            for index, question in enumerate(result.questions) if question.strip()
        ]
        self.events.append(f"summary artifacts build completed: {1 if summary else 0} summary, {len(questions)} questions")
        return SummaryArtifacts(summary=summary, questions=questions)

    def _metadata(self) -> dict[str, Any]:
        return {
            "doc_id": self.document_id, "user_id": self.data.get("user_id"),
            "folder_id": self.data.get("folder_id"), "note_id": self.data.get("note_id"),
            "folder_title": self.data.get("folder_title", ""),
            "note_title": self.data.get("note_title", ""),
        }

    def _id(self, suffix: str) -> str:
        return hashlib.sha256(f"{self.document_id}-{suffix}".encode()).hexdigest()
