from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class IndexChunk:
    chunk_id: str
    document_id: str
    chunk_index: int
    total_chunks: int
    chunk_type: str
    content: str
    embed_text: str
    skip_indexing: bool = False
    skip_reason: str = ""
    prev_chunk_id: str | None = None
    next_chunk_id: str | None = None
    keywords: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentSummary:
    summary: str
    questions: list[str] = field(default_factory=list)
    summary_api_calls: int = 0
    question_api_calls: int = 0
    events: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SummaryDocument:
    document_id: str
    summary_id: str
    content: str
    embed_text: str
    keywords: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QuestionDocument:
    document_id: str
    question_id: str
    content: str
    embed_text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SummaryArtifacts:
    summary: SummaryDocument | None
    questions: list[QuestionDocument] = field(default_factory=list)
