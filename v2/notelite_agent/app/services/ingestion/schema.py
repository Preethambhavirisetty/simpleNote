from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class IngestionRequest(BaseModel):
    """Note payload accepted by queued and synchronous ingestion endpoints."""

    model_config = ConfigDict(extra="allow")

    user_id: str = Field(..., min_length=1, validation_alias=AliasChoices("user_id", "userid"))
    folder_id: str = Field(..., min_length=1)
    note_id: str = Field(..., min_length=1)
    action: Literal["upsert", "delete"] = "upsert"
    text: str = ""

    @model_validator(mode="after")
    def require_text_for_upsert(self):
        if self.action == "upsert" and not self.text.strip():
            raise ValueError("text is required for upsert")
        return self


class IngestionHealthData(BaseModel):
    postgresql: Literal["active", "inactive"]
    qdrant: Literal["active", "inactive"]


class IngestionQueuedData(BaseModel):
    job_id: str
    status: Literal["queued"]


class IngestionApiCalls(BaseModel):
    keyword_dedup: int
    summary: int
    questions: int
    total: int


class IngestionStagesMs(BaseModel):
    chunking: float
    keyword_extraction: float
    summary: float
    questions: float
    document_build: float
    document_ingestion: float
    total: float


class IngestionProcessedData(BaseModel):
    action: Literal["upsert"]
    status: Literal["processed"]
    note_id: str
    text_tokens: int
    chunk_count: int
    top_keywords: list[str]
    entities: list[str]
    summary: str
    questions: list[str]
    api_calls: IngestionApiCalls
    events: list[str]
    stages_ms: IngestionStagesMs


class IngestionDeletedData(BaseModel):
    action: Literal["delete"]
    status: Literal["deleted"]
    doc_id: str
    note_id: str


class IngestionJobStatusData(BaseModel):
    job_id: str
    status: str
    result: Any | None = None
