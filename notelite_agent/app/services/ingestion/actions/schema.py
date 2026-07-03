from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from app.services.chat.actions.schema import PromptActionRequest, RetrievalActionRequest


class ActionChunk(BaseModel):
    chunk_id: str | None = None
    content: str = Field(..., min_length=1)
    chunk_type: str = "content"
    chunk_index: int = 0
    total_chunks: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionKeywordChunk(ActionChunk):
    keywords: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)


class ActionIndexChunk(BaseModel):
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
    keywords: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionSummaryDocument(BaseModel):
    document_id: str
    summary_id: str
    content: str
    embed_text: str
    keywords: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionQuestionDocument(BaseModel):
    document_id: str
    question_id: str
    content: str
    embed_text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentIdentity(BaseModel):
    model_config = ConfigDict(extra="allow")
    user_id: str = Field(..., min_length=1)
    folder_id: str = Field(..., min_length=1)
    note_id: str = Field(..., min_length=1)
    folder_title: str = ""
    note_title: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)


class ChunkPayload(BaseModel):
    text: str = Field(..., min_length=1)


class KeywordsPayload(BaseModel):
    chunks: list[ActionChunk] = Field(..., min_length=1)


class ChunkBuildPayload(DocumentIdentity):
    chunks: list[ActionKeywordChunk] = Field(..., min_length=1)


class IndexChunksPayload(BaseModel):
    document_id: str = Field(..., min_length=1)
    chunks: list[ActionIndexChunk] = Field(..., min_length=1)


class SummaryPayload(BaseModel):
    chunks: list[ActionIndexChunk] = Field(..., min_length=1)


class QuestionsPayload(BaseModel):
    summary: str = Field(..., min_length=1)


class SummaryBuildPayload(DocumentIdentity):
    summary: str = ""
    questions: list[str] = Field(default_factory=list)
    top_keywords: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)


class IndexSummaryPayload(BaseModel):
    summary: ActionSummaryDocument | None = None
    questions: list[ActionQuestionDocument] = Field(default_factory=list)


class DocumentsPayload(ChunkBuildPayload):
    top_keywords: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    note_summary: str = ""


def _example(action_name: str, payload: dict[str, Any]) -> ConfigDict:
    return ConfigDict(json_schema_extra={"example": {"action_name": action_name, "payload": payload}})


class ChunkActionRequest(BaseModel):
    model_config = _example("ingestion.chunk", {"text": "First paragraph.\n\nSecond paragraph."})
    action_name: Literal["ingestion.chunk"]
    payload: ChunkPayload


class KeywordsActionRequest(BaseModel):
    model_config = _example("ingestion.keywords", {"chunks": [{"chunk_id": "0", "content": "Qdrant stores note chunks."}]})
    action_name: Literal["ingestion.keywords"]
    payload: KeywordsPayload


class ChunkBuildActionRequest(BaseModel):
    action_name: Literal["ingestion.chunk_build"]
    payload: ChunkBuildPayload


class IndexChunksActionRequest(BaseModel):
    action_name: Literal["ingestion.index_chunks"]
    payload: IndexChunksPayload


class SummaryActionRequest(BaseModel):
    action_name: Literal["ingestion.summary"]
    payload: SummaryPayload


class QuestionsActionRequest(BaseModel):
    action_name: Literal["ingestion.questions"]
    payload: QuestionsPayload


class SummaryBuildActionRequest(BaseModel):
    action_name: Literal["ingestion.summary_build"]
    payload: SummaryBuildPayload


class IndexSummaryActionRequest(BaseModel):
    action_name: Literal["ingestion.index_summary"]
    payload: IndexSummaryPayload


class DocumentsActionRequest(BaseModel):
    action_name: Literal["ingestion.documents"]
    payload: DocumentsPayload


PipelineActionRequest = Annotated[
    Union[
        ChunkActionRequest, KeywordsActionRequest, ChunkBuildActionRequest,
        IndexChunksActionRequest, SummaryActionRequest, QuestionsActionRequest,
        SummaryBuildActionRequest, IndexSummaryActionRequest, DocumentsActionRequest,
        RetrievalActionRequest, PromptActionRequest,
    ],
    Field(discriminator="action_name"),
]


class PipelineActionResponse(BaseModel):
    action_name: str
    result: dict[str, Any]
