from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _empty_to_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


_BLOCKED_KEYS = {"__proto__", "constructor", "prototype"}


def _validate_runtime_context_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        raise ValueError("runtime_context nesting exceeds 8 levels")
    if isinstance(value, dict):
        if len(value) > 128:
            raise ValueError("runtime_context object has too many keys")
        cleaned: dict[str, Any] = {}
        for key, nested in value.items():
            key_str = str(key)
            if key_str in _BLOCKED_KEYS:
                raise ValueError(f"runtime_context contains blocked key: {key_str}")
            cleaned[key_str] = _validate_runtime_context_value(nested, depth=depth + 1)
        return cleaned
    if isinstance(value, list):
        if len(value) > 512:
            raise ValueError("runtime_context list is too large")
        return [_validate_runtime_context_value(item, depth=depth + 1) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class RuntimeMessageModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(..., pattern="^(system|user|assistant)$")
    content: str = Field("", max_length=12_000)


class TruncationPolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_artifact_chars: int = Field(2500, ge=200, le=20000)
    score_weights: dict[str, float] = Field(default_factory=dict)
    freshness_half_life_seconds: float = Field(3600.0, gt=0)


class ToolPolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowlist: list[str] = Field(default_factory=list, max_length=256)
    denylist: list[str] = Field(default_factory=list, max_length=256)
    required_tools: dict[str, list[str]] = Field(default_factory=dict)
    argument_injection: dict[str, dict[str, str]] = Field(default_factory=dict)


class PlannerDefaultsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    max_tokens: int = Field(1500, ge=128, le=16000)


class ReviewerDefaultsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    max_tokens: int = Field(1200, ge=128, le=16000)
    max_cycles: int = Field(2, ge=0, le=20)
    reject_action: str = Field("replan", pattern="^(replan|abort)$")


class AgentPolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_executor_iterations: int = Field(12, ge=1, le=100)
    max_review_cycles: int = Field(2, ge=0, le=20)
    max_tool_calls_per_step: int = Field(4, ge=1, le=20)
    max_context_tokens: int = Field(12000, ge=1000, le=200000)
    llm_timeout_seconds: float = Field(60.0, ge=1.0, le=600.0)
    tool_timeout_seconds: float = Field(120.0, ge=1.0, le=1800.0)
    max_retained_artifacts: int = Field(24, ge=0, le=200)
    max_retained_tool_calls: int = Field(40, ge=0, le=300)
    max_retained_events: int = Field(80, ge=0, le=500)
    tool_discovery_cache_size: int = Field(16, ge=0, le=200)
    reject_action: str = Field("replan", pattern="^(replan|abort)$")
    destructive_tools: list[str] = Field(default_factory=list, max_length=256)
    require_destructive_confirmation: bool = True
    enable_fast_path: bool = True
    enable_planner: bool = True
    enable_reviewer: bool = True
    truncation: TruncationPolicyModel = Field(default_factory=TruncationPolicyModel)
    model: str | None = Field(default=None, max_length=255)
    instructions: str = Field("", max_length=60_000)
    tools: ToolPolicyModel = Field(default_factory=ToolPolicyModel)
    planner: PlannerDefaultsModel = Field(default_factory=PlannerDefaultsModel)
    reviewer: ReviewerDefaultsModel = Field(default_factory=ReviewerDefaultsModel)


class ToolDiscoveryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str = Field("fallback", max_length=32)
    search_url: str = Field("", max_length=2000)
    collections: list[str] = Field(default_factory=list, max_length=32)
    owner_scope: str = Field("", max_length=64)
    indexed: bool = False


class McpServerModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field("default", min_length=1, max_length=120)
    url: str = Field("", max_length=2000)
    auth_token: str = Field("", max_length=8000)
    timeout_seconds: float = Field(120.0, ge=1.0, le=1800.0)
    verify_ssl: bool = True
    proxy_url: str = Field("", max_length=2000)
    tool_discovery: ToolDiscoveryModel = Field(default_factory=ToolDiscoveryModel)


class McpConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field("", max_length=2000)
    auth_token: str = Field("", max_length=8000)
    timeout_seconds: float = Field(120.0, ge=1.0, le=1800.0)
    verify_ssl: bool = True
    servers: list[McpServerModel] = Field(default_factory=list, max_length=32)


class LlmConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(..., min_length=1, max_length=2000)
    api_key: str = Field("", max_length=8000)
    model: str = Field(..., min_length=1, max_length=255)
    send_auth_header: bool = True
    default_max_tokens: int = Field(1024, ge=1, le=64000)
    temperature: float = Field(0.2, ge=0.0, le=2.0)
    top_p: float = Field(0.9, ge=0.0, le=1.0)
    top_k: int = Field(40, ge=0, le=500)
    seed: int = Field(0xFFFFFFFF)

    @field_validator("default_max_tokens", "top_k", "seed", mode="before")
    @classmethod
    def coerce_empty_int(cls, value: Any) -> Any:
        return _empty_to_none(value)

    @field_validator("temperature", "top_p", mode="before")
    @classmethod
    def coerce_empty_float(cls, value: Any) -> Any:
        return _empty_to_none(value)


class AgentConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field("agent", min_length=1, max_length=255)
    prompts: dict[str, str] = Field(default_factory=dict)
    prompts_inline: dict[str, str] = Field(default_factory=dict)
    llm: LlmConfigModel
    mcp: McpConfigModel = Field(default_factory=McpConfigModel)
    policy: AgentPolicyModel = Field(default_factory=AgentPolicyModel)

    @field_validator("prompts", "prompts_inline")
    @classmethod
    def validate_prompt_keys(cls, value: dict[str, str]) -> dict[str, str]:
        allowed = {"planner", "executor", "reviewer"}
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"unknown prompt role(s): {', '.join(unknown)}")
        return value

    @model_validator(mode="after")
    def validate_prompt_sources(self) -> "AgentConfigModel":
        if not (self.prompts or self.prompts_inline):
            raise ValueError("at least one prompt source must be configured")
        return self


class RunRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=12000)
    session_id: str = Field("", max_length=255)
    history: list[RuntimeMessageModel] = Field(default_factory=list, max_length=100)
    runtime_context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("runtime_context", mode="before")
    @classmethod
    def validate_runtime_context(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("runtime_context must be an object")
        return _validate_runtime_context_value(value)
