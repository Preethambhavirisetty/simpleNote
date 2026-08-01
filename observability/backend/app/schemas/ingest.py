from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Level = Literal["DEBUG", "INFO", "WARN", "ERROR"]


class RunStart(BaseModel):
    run_key: str = Field(max_length=64)
    conversation_id: str | None = Field(default=None, max_length=128)
    question: str | None = None
    started_at: datetime | None = None
    metadata: dict[str, Any] | None = None


class LogLine(BaseModel):
    seq: int = Field(ge=0)
    ts: datetime | None = None
    level: Level = "INFO"
    phase: str | None = Field(default=None, max_length=64)
    message: str
    source: str | None = Field(default=None, max_length=255)
    data: dict[str, Any] | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    # tracked values emitted by this line; any name, any JSON-able value
    track: dict[str, Any] | None = None


class LogBatch(BaseModel):
    logs: list[LogLine]


class RunFinish(BaseModel):
    status: Literal["ok", "error"] = "ok"
    final_answer: str | None = None
    error_message: str | None = None
    ended_at: datetime | None = None


class FieldDefPatch(BaseModel):
    label: str | None = Field(default=None, max_length=128)
    unit: str | None = Field(default=None, max_length=16)
    pinned: bool | None = None
    display_order: int | None = None
    aggregate: Literal["last", "first", "sum", "avg", "max", "min", "count"] | None = None
