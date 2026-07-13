from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agent_workflow.exploration_profile import validate_runtime_context_profile


def _empty_to_none(value: Any) -> Any:
    """Helper for empty to none."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


_BLOCKED_KEYS = {"__proto__", "constructor", "prototype"}


def _validate_runtime_context_value(value: Any, *, depth: int = 0) -> Any:
    """Validate runtime context value and raise or return errors when invalid."""
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
    """Validated chat history message supplied by a caller."""
    model_config = ConfigDict(extra="forbid")

    role: str = Field(..., pattern="^(system|user|assistant)$")
    content: str = Field("", max_length=12_000)


class TruncationPolicyModel(BaseModel):
    """Validation model for artifact truncation settings."""
    model_config = ConfigDict(extra="forbid")

    # Ceilings are generous so high-resource deployments can raise budgets
    # (e.g. large report/table tools) without hitting validation limits.
    max_artifact_chars: int = Field(2500, ge=200, le=200000)
    max_string_field_chars: int = Field(400, ge=200, le=200000)
    max_fact_chars: int = Field(2000, ge=200, le=200000)
    max_list_rows_visible: int = Field(100, ge=1, le=50000)
    dict_list_budget_reserve: int = Field(96, ge=0, le=1000)
    dict_list_min_budget: int = Field(200, ge=50, le=10000)
    score_weights: dict[str, float] = Field(default_factory=dict)
    freshness_half_life_seconds: float = Field(3600.0, gt=0)


class ToolPolicyModel(BaseModel):
    """Validation model for allowed, denied, and required tools."""
    model_config = ConfigDict(extra="forbid")

    allowlist: list[str] = Field(default_factory=list, max_length=256)
    denylist: list[str] = Field(default_factory=list, max_length=256)
    required_tools: dict[str, list[str]] = Field(default_factory=dict)
    argument_injection: dict[str, dict[str, str]] = Field(default_factory=dict)


class PlannerDefaultsModel(BaseModel):
    """Validation model for planner behavior settings."""
    model_config = ConfigDict(extra="forbid")

    # None = inherit the flat `enable_planner` flag (which itself defaults True).
    # This keeps nested/flat precedence explicit: nested wins only when it is set.
    enabled: bool | None = None
    max_tokens: int = Field(1500, ge=128, le=16000)


class ReviewerDefaultsModel(BaseModel):
    """Validation model for reviewer behavior settings."""
    model_config = ConfigDict(extra="forbid")

    # None = inherit the flat `enable_reviewer` flag (which itself defaults True).
    # This keeps nested/flat precedence explicit: nested wins only when it is set.
    enabled: bool | None = None
    max_tokens: int = Field(1200, ge=128, le=16000)
    # When the reviewer is enabled it always runs at least once, so the cap
    # starts at 1. To skip review entirely, set enabled/enable_reviewer to false.
    # None = inherit the flat `max_review_cycles` (which itself defaults to 2),
    # so nested wins only when explicitly set (mirrors the enabled flag).
    max_cycles: int | None = Field(None, ge=1, le=20)
    # REJECT returns the best available draft and stops. Replan-on-reject is not wired.
    # Accept the legacy "replan" value so pre-existing configs still validate.
    # Reject currently always aborts (replan-on-reject is not wired), so "replan"
    # is preserved but behaves as "abort".
    reject_action: str = Field("abort", pattern="^(replan|abort)$")
    # always: review every run; on_risk: review only runs with failed/denied
    # tool calls or errors — clean runs skip the reviewer LLM call.
    mode: str = Field("always", pattern="^(always|on_risk)$")


class ExecutorDefaultsModel(BaseModel):
    """Validation model for executor LLM output and display limits."""
    model_config = ConfigDict(extra="forbid")

    choose_action_max_tokens: int = Field(1200, ge=128, le=16000)
    native_tool_max_tokens: int = Field(1200, ge=128, le=16000)
    synthesize_max_tokens: int = Field(2000, ge=128, le=16000)
    max_native_tools: int = Field(7, ge=1, le=200)
    tool_description_max_chars: int = Field(1024, ge=128, le=16000)
    fallback_artifact_limit: int = Field(5, ge=1, le=200)
    mechanical_artifact_limit: int = Field(12, ge=1, le=200)
    mechanical_line_limit: int = Field(120, ge=1, le=2000)
    fallback_summary_chars: int = Field(400, ge=100, le=20000)


class FinalizerDefaultsModel(BaseModel):
    """Validation model for final answer rendering limits."""
    model_config = ConfigDict(extra="forbid")

    max_tokens: int = Field(2000, ge=128, le=16000)
    max_artifact_lines: int = Field(12, ge=1, le=200)
    artifact_line_max_chars: int = Field(1200, ge=200, le=20000)


class SummaryDefaultsModel(BaseModel):
    """Validation model for the in-loop running-summary (memory compaction) node."""
    model_config = ConfigDict(extra="forbid")

    compact_after_artifacts: int = Field(16, ge=1, le=200)
    keep_after_summary: int = Field(6, ge=0, le=200)
    max_cycles: int = Field(3, ge=1, le=20)
    max_tokens: int = Field(700, ge=128, le=16000)


class RevisionDefaultsModel(BaseModel):
    """Validation model for the bounded revision node."""
    model_config = ConfigDict(extra="forbid")

    max_cycles: int = Field(1, ge=1, le=5)


class RouterDefaultsModel(BaseModel):
    """Validation model for fast-path router limits."""
    model_config = ConfigDict(extra="forbid")

    fast_path_max_tokens: int = Field(512, ge=128, le=16000)
    fast_path_max_query_chars: int = Field(180, ge=50, le=2000)
    fast_path_max_query_words: int = Field(24, ge=5, le=500)
    fast_path_history_messages: int = Field(4, ge=0, le=100)
    fast_path_history_content_chars: int = Field(1000, ge=100, le=12000)
    merge_state_max_events: int = Field(80, ge=10, le=500)


class ContextLimitsModel(BaseModel):
    """Validation model for prompt assembly display limits."""
    model_config = ConfigDict(extra="forbid")

    system_budget_padding: int = Field(50, ge=0, le=1000)
    min_artifact_budget_tokens: int = Field(200, ge=0, le=10000)
    trim_section_min_chars: int = Field(200, ge=50, le=10000)
    max_tools_in_prompt: int = Field(7, ge=1, le=200)
    max_tool_calls_in_prompt: int = Field(5, ge=1, le=200)
    max_artifacts_in_prompt: int = Field(10, ge=1, le=200)
    max_history_messages: int = Field(6, ge=0, le=100)
    history_preview_head_chars: int = Field(400, ge=0, le=20000)
    history_preview_tail_chars: int = Field(400, ge=0, le=20000)
    artifact_summary_ratio: float = Field(0.75, ge=0.1, le=1.0)
    artifact_summary_min_chars: int = Field(1200, ge=200, le=20000)


class AgentPolicyModel(BaseModel):
    """Validation model for workflow policy settings."""
    model_config = ConfigDict(extra="forbid")

    max_executor_iterations: int = Field(12, ge=1, le=100)
    # Legacy flat alias for reviewer.max_cycles; an enabled reviewer runs at
    # least once, so the cap starts at 1. Disable review via enable_reviewer.
    max_review_cycles: int = Field(2, ge=1, le=20)
    # Cap on reviewer-driven re-entries to the executor for missing evidence.
    # 0 disables re-exploration (REVISE then only routes to text revision).
    max_explore_cycles: int = Field(1, ge=0, le=10)
    max_tool_calls_per_step: int = Field(4, ge=1, le=20)
    max_no_progress_turns: int = Field(3, ge=0, le=20)
    min_progress_score: float = Field(0.15, ge=0.0, le=1.0)
    max_context_tokens: int = Field(12000, ge=1000, le=200000)
    llm_timeout_seconds: float = Field(60.0, ge=1.0, le=600.0)
    tool_timeout_seconds: float = Field(120.0, ge=1.0, le=1800.0)
    max_retained_artifacts: int = Field(24, ge=0, le=200)
    max_retained_tool_calls: int = Field(40, ge=0, le=300)
    max_retained_events: int = Field(80, ge=0, le=500)
    tool_discovery_cache_size: int = Field(16, ge=0, le=200)
    # REJECT returns the best available draft and stops. Replan-on-reject is not wired.
    # Accept the legacy "replan" value so pre-existing configs still validate.
    # Reject currently always aborts (replan-on-reject is not wired), so "replan"
    # is preserved but behaves as "abort".
    reject_action: str = Field("abort", pattern="^(replan|abort)$")
    destructive_tools: list[str] = Field(default_factory=list, max_length=256)
    require_destructive_confirmation: bool = True
    enable_fast_path: bool = True
    render_final_answer: bool = True
    enforce_grounding: bool = False
    enable_planner: bool = True
    enable_reviewer: bool = True
    enable_running_summary: bool = False
    cross_turn_artifact_persistence: bool = False
    artifact_store_ttl_seconds: int = Field(86400, ge=60, le=604800)
    require_tool_on_follow_up: bool = True
    enable_conversation_memory: bool = True
    enable_follow_up_reuse: bool = True
    enable_playbooks: bool = True
    conversation_memory_max_slots: int = Field(10, ge=0, le=64)
    truncation: TruncationPolicyModel = Field(default_factory=TruncationPolicyModel)
    model: str | None = Field(default=None, max_length=255)
    instructions: str = Field("", max_length=60_000)
    tools: ToolPolicyModel = Field(default_factory=ToolPolicyModel)
    planner: PlannerDefaultsModel = Field(default_factory=PlannerDefaultsModel)
    reviewer: ReviewerDefaultsModel = Field(default_factory=ReviewerDefaultsModel)
    executor: ExecutorDefaultsModel = Field(default_factory=ExecutorDefaultsModel)
    finalizer: FinalizerDefaultsModel = Field(default_factory=FinalizerDefaultsModel)
    summary: SummaryDefaultsModel = Field(default_factory=SummaryDefaultsModel)
    revision: RevisionDefaultsModel = Field(default_factory=RevisionDefaultsModel)
    router: RouterDefaultsModel = Field(default_factory=RouterDefaultsModel)
    context: ContextLimitsModel = Field(default_factory=ContextLimitsModel)


class ToolDiscoveryModel(BaseModel):
    """Validation model for semantic MCP tool discovery settings."""
    model_config = ConfigDict(extra="forbid")

    mode: str = Field("fallback", max_length=32)
    search_url: str = Field("", max_length=2000)
    collections: list[str] = Field(default_factory=list, max_length=32)
    owner_scope: str = Field("", max_length=64)
    indexed: bool = False


class McpServerModel(BaseModel):
    """Validation model for one MCP server definition."""
    model_config = ConfigDict(extra="forbid")

    name: str = Field("default", min_length=1, max_length=120)
    url: str = Field("", max_length=2000)
    auth_token: str = Field("", max_length=8000)
    timeout_seconds: float = Field(120.0, ge=1.0, le=1800.0)
    verify_ssl: bool = True
    proxy_url: str = Field("", max_length=2000)
    tool_discovery: ToolDiscoveryModel = Field(default_factory=ToolDiscoveryModel)


class McpConfigModel(BaseModel):
    """Validation model for MCP connection settings."""
    model_config = ConfigDict(extra="forbid")

    url: str = Field("", max_length=2000)
    auth_token: str = Field("", max_length=8000)
    timeout_seconds: float = Field(120.0, ge=1.0, le=1800.0)
    verify_ssl: bool = True
    servers: list[McpServerModel] = Field(default_factory=list, max_length=32)


class LlmConfigModel(BaseModel):
    """Validation model for LLM connection and sampling settings."""
    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(..., min_length=1, max_length=2000)
    api_key: str = Field("", max_length=8000)
    model: str = Field(..., min_length=1, max_length=255)
    send_auth_header: bool = True
    default_max_tokens: int = Field(1024, ge=1, le=64000)
    temperature: float = Field(0.2, ge=0.0, le=2.0)
    top_p: float = Field(0.9, ge=0.0, le=1.0)
    top_k: int = Field(40, ge=0, le=500)
    # None (default) = do not send a seed; the backend samples with a fresh RNG
    # per request. Set an integer only when reproducible output is explicitly
    # wanted — a pinned seed makes every identical prompt produce the identical
    # completion (including identical mistakes on retries).
    seed: int | None = Field(None)
    # Use the OpenAI tools/tool_calls contract for executor tool selection when
    # the provider supports it; falls back to JSON-in-text on failure.
    native_tool_calling: bool = False

    @field_validator("default_max_tokens", "top_k", "seed", mode="before")
    @classmethod
    def coerce_empty_int(cls, value: Any) -> Any:
        """Coerce empty int."""
        return _empty_to_none(value)

    @field_validator("temperature", "top_p", mode="before")
    @classmethod
    def coerce_empty_float(cls, value: Any) -> Any:
        """Coerce empty float."""
        return _empty_to_none(value)


class CheckpointerResourceModel(BaseModel):
    """Validation model for durable checkpoint storage."""
    model_config = ConfigDict(extra="forbid")

    mode: str = Field("", pattern="^(|memory|redis|postgres|postgresql)$")
    url: str = Field("", max_length=2000)


class ToolIndexResourceModel(BaseModel):
    """Validation model for shared semantic tool index settings."""
    model_config = ConfigDict(extra="forbid")

    search_url: str = Field("", max_length=2000)
    collections: list[str] = Field(default_factory=list, max_length=32)
    owner_scope: str = Field("", max_length=64)


class ResourcesModel(BaseModel):
    """Shared infrastructure connections referenced by the runtime.

    checkpointer: durable saver backing HITL resume (redis/postgres).
    tool_index: default semantic tool-search endpoint applied to MCP servers
    that do not define their own tool_discovery.search_url.
    """

    model_config = ConfigDict(extra="forbid")

    checkpointer: CheckpointerResourceModel = Field(default_factory=CheckpointerResourceModel)
    tool_index: ToolIndexResourceModel = Field(default_factory=ToolIndexResourceModel)


class AgentConfigModel(BaseModel):
    """Validation model for a full agent workflow configuration."""
    model_config = ConfigDict(extra="forbid")

    name: str = Field("agent", min_length=1, max_length=255)
    prompts: dict[str, str] = Field(default_factory=dict)
    prompts_inline: dict[str, str] = Field(default_factory=dict)
    llm: LlmConfigModel
    mcp: McpConfigModel = Field(default_factory=McpConfigModel)
    policy: AgentPolicyModel = Field(default_factory=AgentPolicyModel)
    resources: ResourcesModel = Field(default_factory=ResourcesModel)

    @field_validator("prompts", "prompts_inline")
    @classmethod
    def validate_prompt_keys(cls, value: dict[str, str]) -> dict[str, str]:
        """Validate prompt keys and raise or return errors when invalid."""
        allowed = {"planner", "executor", "reviewer"}
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"unknown prompt role(s): {', '.join(unknown)}")
        return value

    @model_validator(mode="after")
    def validate_prompt_sources(self) -> "AgentConfigModel":
        """Validate prompt sources and raise or return errors when invalid."""
        if not (self.prompts or self.prompts_inline):
            raise ValueError("at least one prompt source must be configured")
        return self


class RunRequestModel(BaseModel):
    """Validation model for incoming workflow run requests."""
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=12000)
    session_id: str = Field("", max_length=255)
    history: list[RuntimeMessageModel] = Field(default_factory=list, max_length=100)
    runtime_context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("runtime_context", mode="before")
    @classmethod
    def validate_runtime_context(cls, value: Any) -> dict[str, Any]:
        """Validate runtime context and raise or return errors when invalid."""
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("runtime_context must be an object")
        cleaned = _validate_runtime_context_value(value)
        return validate_runtime_context_profile(cleaned)
