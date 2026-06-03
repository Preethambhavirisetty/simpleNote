from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from app.services.chat.actions.schema import PromptActionRequest, RetrievalActionRequest


class ActionChunk(BaseModel):
    chunk_id: str | None = None
    content: str = Field(..., min_length=1)


class ActionKeywordChunk(ActionChunk):
    keywords: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)


class ChunkPayload(BaseModel):
    text: str = Field(..., min_length=1)


class KeywordsPayload(BaseModel):
    chunks: list[ActionChunk] = Field(..., min_length=1)


class SummaryPayload(BaseModel):
    chunks: list[ActionChunk] = Field(..., min_length=1)


class QuestionsPayload(BaseModel):
    summary: str = Field(..., min_length=1)


class DocumentsPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    user_id: str = Field(..., min_length=1)
    folder_id: str = Field(..., min_length=1)
    note_id: str = Field(..., min_length=1)
    folder_title: str = ""
    note_title: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    chunks: list[ActionKeywordChunk] = Field(..., min_length=1)
    top_keywords: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    note_summary: str = ""


class ChunkActionRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "action_name": "ingestion.chunk",
            "payload": {"text": "First paragraph.\n\nSecond paragraph."},
        }
    })

    action_name: Literal["ingestion.chunk"]
    payload: ChunkPayload


class KeywordsActionRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "action_name": "ingestion.keywords",
            "payload": {"chunks": [{"chunk_id": "0", "content": "Qdrant stores note chunks for retrieval."}]},
        }
    })

    action_name: Literal["ingestion.keywords"]
    payload: KeywordsPayload


class SummaryActionRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "action_name": "ingestion.summary",
            "payload": {"chunks": [{"chunk_id": "0", "content": "Gerard lives in the Ooster-Waagen Straet."}]},
        }
    })

    action_name: Literal["ingestion.summary"]
    payload: SummaryPayload


class QuestionsActionRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "action_name": "ingestion.questions",
            "payload": {"summary": "Gerard lives in the Ooster-Waagen Straet and helps Eli."},
        }
    })

    action_name: Literal["ingestion.questions"]
    payload: QuestionsPayload


class DocumentsActionRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "action_name": "ingestion.documents",
            "payload": {
                "user_id": "user-1",
                "folder_id": "folder-1",
                "note_id": "note-1",
                "note_title": "Sample note",
                "chunks": [{"chunk_id": "0", "content": "Qdrant stores note chunks.", "keywords": ["Qdrant"], "entities": ["Qdrant"]}],
                "top_keywords": ["Qdrant"],
                "entities": ["Qdrant"],
                "questions": ["What stores note chunks?"],
                "note_summary": "Qdrant stores note chunks.",
            },
        }
    })

    action_name: Literal["ingestion.documents"]
    payload: DocumentsPayload


PipelineActionRequest = Annotated[
    Union[
        ChunkActionRequest,
        KeywordsActionRequest,
        SummaryActionRequest,
        QuestionsActionRequest,
        DocumentsActionRequest,
        RetrievalActionRequest,
        PromptActionRequest,
    ],
    Field(discriminator="action_name"),
]


class PipelineActionResponse(BaseModel):
    action_name: str
    result: dict[str, Any]
