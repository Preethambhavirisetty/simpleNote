from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentWorkflowMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(..., pattern="^(system|user|assistant)$")
    content: str = Field("", max_length=12000)


class AgentWorkflowRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=12000)
    session_id: str = Field("", max_length=255)
    history: list[AgentWorkflowMessage] = Field(default_factory=list, max_length=100)
    runtime_context: dict[str, Any] = Field(default_factory=dict)
    config_path: str | None = Field(default=None, max_length=2000)
    config: dict[str, Any] | None = None
    runtime_overrides: dict[str, Any] | None = None


class AgentWorkflowRuntimeBundleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=12000)
    session_id: str = Field("", max_length=255)
    history: list[AgentWorkflowMessage] = Field(default_factory=list, max_length=100)
    runtime_context: dict[str, Any] = Field(default_factory=dict)
    runtime_bundle: dict[str, Any] = Field(default_factory=dict)


class AgentWorkflowResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str = Field(..., min_length=1, max_length=512)
    approved: bool
    config_path: str | None = Field(default=None, max_length=2000)
    config: dict[str, Any] | None = None
    runtime_overrides: dict[str, Any] | None = None
