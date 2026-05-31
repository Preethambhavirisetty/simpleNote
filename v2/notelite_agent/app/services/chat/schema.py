from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator


class ChatHistoryMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str = Field(..., min_length=1)


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=10_000)
    k: int = Field(5, ge=1, le=50)
    user_id: str = Field(..., min_length=1)
    role: str = Field("user")
    tenant_id: Optional[str] = None
    conversation_id: Optional[str] = Field(None, description="Existing conversation to continue")
    conversation_title: Optional[str] = Field(None, max_length=255)

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        role = v.strip().lower()
        if role not in {"user", "admin"}:
            raise ValueError("role must be 'user' or 'admin'")
        return role

    @field_validator("tenant_id")
    @classmethod
    def validate_tenant_id(cls, v: Optional[str], info):
        role = (info.data.get("role") or "user").lower()
        if role != "admin" and not v:
            raise ValueError("tenant_id is required for non-admin requests.")
        return v


class ChatStageRequest(BaseModel):
    """Side-effect-free inputs for inspecting the chat pipeline stages."""

    query: str = Field(..., min_length=1, max_length=10_000)
    k: int = Field(5, ge=1, le=50)
    user_id: str = Field(..., min_length=1)
    role: Literal["user", "admin"] = "user"
    history: list[ChatHistoryMessage] = Field(default_factory=list)


class ConversationHistoryRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    conversation_id: str = Field(..., min_length=1)


class ChatCompletionRequest(BaseModel):
    """Messages for a direct non-RAG chat completion."""

    messages: list[ChatHistoryMessage] = Field(..., min_length=1)


class ChatCompletionData(BaseModel):
    response: str


class RetrievalHit(BaseModel):
    id: str
    doc_id: Optional[str] = None
    score: float
    text: str


class RetrievalDiagnosticsData(BaseModel):
    query: str
    metadata_filter: Optional[dict[str, str]] = None
    summary_hits: list[RetrievalHit]
    summary_doc_ids: list[str]
    chunk_search_scope: str
    chunk_hits: list[RetrievalHit]
    reranker_enabled: bool
    reranked_hits: list[RetrievalHit]
    selected_context: list[str]
    source_ids: list[str]
    context_budget_tokens: int
    remaining_context_budget_tokens: int


class PromptStageData(BaseModel):
    retrieval: RetrievalDiagnosticsData
    history: list[ChatHistoryMessage]
    messages: list[ChatHistoryMessage]
    prompt_tokens_estimate: int


class ConversationHistoryData(BaseModel):
    conversation_id: str
    messages: list[dict]
    events: list[str]
