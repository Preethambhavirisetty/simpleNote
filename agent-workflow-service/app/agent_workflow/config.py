from __future__ import annotations

import os
import re
import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.agent_workflow.runtime_schema import AgentConfigModel


_ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _resolve_env(value: str) -> str:
    """Resolve env from config or runtime input."""
    def replacer(match: re.Match[str]) -> str:
        """Replace one ${ENV_NAME} placeholder with its environment value."""
        key = match.group(1)
        return os.getenv(key, "")

    return _ENV_PATTERN.sub(replacer, value)


def _resolve_env_deep(obj: Any) -> Any:
    """Resolve env deep from config or runtime input."""
    if isinstance(obj, str):
        return _resolve_env(obj)
    if isinstance(obj, dict):
        return {k: _resolve_env_deep(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_deep(v) for v in obj]
    return obj


def _as_bool(value: Any, default: bool = False) -> bool:
    """Coerce a config value into bool form."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return bool(value)


def _as_int(value: Any, default: int) -> int:
    """Coerce a config value into int form."""
    if value is None:
        return default
    if isinstance(value, str) and not value.strip():
        return default
    return int(value)


def _as_float(value: Any, default: float) -> float:
    """Coerce a config value into float form."""
    if value is None:
        return default
    if isinstance(value, str) and not value.strip():
        return default
    return float(value)


@dataclass
class TruncationPolicy:
    """Runtime settings for trimming and scoring artifacts."""
    max_artifact_chars: int = 2500
    max_string_field_chars: int = 400
    max_list_rows_visible: int = 100
    dict_list_budget_reserve: int = 96
    dict_list_min_budget: int = 200
    score_weights: dict[str, float] = field(
        default_factory=lambda: {
            "relevance": 0.4,
            "freshness": 0.2,
            "uniqueness": 0.2,
            "actionability": 0.2,
        }
    )
    freshness_half_life_seconds: float = 3600.0


@dataclass
class ToolPolicy:
    """Runtime settings for tool allowlists, denylists, and injection."""
    allowlist: list[str] = field(default_factory=list)
    denylist: list[str] = field(default_factory=list)
    required_tools: dict[str, list[str]] = field(default_factory=dict)
    argument_injection: dict[str, dict[str, str]] = field(default_factory=dict)


@dataclass
class PlannerDefaults:
    """Runtime planner defaults."""
    enabled: bool = True
    max_tokens: int = 1500


@dataclass
class ReviewerDefaults:
    """Runtime reviewer defaults."""
    enabled: bool = True
    max_tokens: int = 2400
    max_cycles: int = 2
    # NOTE: reject_action is currently informational only. A REJECT verdict
    # returns the best-available draft and stops; the graph does not route back
    # to the planner, so "replan" is not yet wired. "abort" reflects the real
    # behavior. Keep this until replan-on-reject is implemented.
    reject_action: str = "replan"
    mode: str = "always"  # always | on_risk


@dataclass
class ExecutorDefaults:
    """Runtime executor LLM output and display limits."""
    choose_action_max_tokens: int = 1200
    native_tool_max_tokens: int = 1200
    synthesize_max_tokens: int = 2000
    max_native_tools: int = 7
    tool_description_max_chars: int = 1024
    fallback_artifact_limit: int = 5
    mechanical_artifact_limit: int = 12
    mechanical_line_limit: int = 120
    fallback_summary_chars: int = 400


@dataclass
class FinalizerDefaults:
    """Runtime finalizer rendering limits."""
    max_tokens: int = 2000
    max_artifact_lines: int = 12
    artifact_line_max_chars: int = 1200


@dataclass
class RouterDefaults:
    """Runtime fast-path router limits."""
    fast_path_max_tokens: int = 512
    fast_path_max_query_chars: int = 180
    fast_path_max_query_words: int = 24
    fast_path_history_messages: int = 4
    fast_path_history_content_chars: int = 1000
    merge_state_max_events: int = 80


@dataclass
class ContextLimits:
    """Runtime prompt assembly display limits."""
    system_budget_padding: int = 50
    min_artifact_budget_tokens: int = 200
    trim_section_min_chars: int = 200
    max_tools_in_prompt: int = 7
    max_tool_calls_in_prompt: int = 5
    max_artifacts_in_prompt: int = 10
    max_history_messages: int = 6
    history_preview_head_chars: int = 400
    history_preview_tail_chars: int = 400
    artifact_summary_ratio: float = 0.75
    artifact_summary_min_chars: int = 1200


@dataclass
class AgentPolicy:
    """Runtime policy controlling workflow limits and gates."""
    max_executor_iterations: int = 12
    max_review_cycles: int = 2
    max_tool_calls_per_step: int = 4
    max_context_tokens: int = 12000
    llm_timeout_seconds: float = 60.0
    tool_timeout_seconds: float = 120.0
    max_retained_artifacts: int = 24
    max_retained_tool_calls: int = 40
    max_retained_events: int = 80
    tool_discovery_cache_size: int = 16
    # See ReviewerDefaults.reject_action: "replan" is not yet wired; a REJECT
    # verdict returns the best-available draft. "abort" is the honest setting.
    reject_action: str = "replan"  # replan (not yet implemented) | abort
    destructive_tools: list[str] = field(default_factory=list)
    require_destructive_confirmation: bool = True
    enable_fast_path: bool = True
    render_final_answer: bool = True
    enforce_grounding: bool = False
    enable_planner: bool = True
    enable_reviewer: bool = True
    cross_turn_artifact_persistence: bool = False
    artifact_store_ttl_seconds: int = 86400
    require_tool_on_follow_up: bool = True
    truncation: TruncationPolicy = field(default_factory=TruncationPolicy)
    tools: ToolPolicy = field(default_factory=ToolPolicy)
    planner: PlannerDefaults = field(default_factory=PlannerDefaults)
    reviewer: ReviewerDefaults = field(default_factory=ReviewerDefaults)
    executor: ExecutorDefaults = field(default_factory=ExecutorDefaults)
    finalizer: FinalizerDefaults = field(default_factory=FinalizerDefaults)
    router: RouterDefaults = field(default_factory=RouterDefaults)
    context: ContextLimits = field(default_factory=ContextLimits)
    model: str | None = None
    instructions: str = ""


@dataclass
class ToolDiscoveryConfig:
    """Runtime settings for semantic tool discovery."""
    mode: str = "fallback"
    search_url: str = ""
    collections: list[str] = field(default_factory=list)
    owner_scope: str = ""
    indexed: bool = False


@dataclass
class McpServerConfig:
    """Runtime settings for one MCP server."""
    name: str = "default"
    url: str = ""
    auth_token: str = ""
    timeout_seconds: float = 120.0
    verify_ssl: bool = True
    proxy_url: str = ""
    tool_discovery: ToolDiscoveryConfig = field(default_factory=ToolDiscoveryConfig)


@dataclass
class LlmConfig:
    """Runtime settings for the LLM provider."""
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    send_auth_header: bool = True
    default_max_tokens: int = 1024
    temperature: float = 0.2
    top_p: float = 0.9
    top_k: int = 40
    seed: int = 0xFFFFFFFF
    native_tool_calling: bool = False


@dataclass
class McpConfig:
    """Runtime settings for MCP providers."""
    url: str = ""
    auth_token: str = ""
    timeout_seconds: float = 120.0
    verify_ssl: bool = True
    servers: list[McpServerConfig] = field(default_factory=list)


@dataclass
class CheckpointerResource:
    """Runtime checkpointer backend settings."""
    mode: str = ""  # "" (unset) | memory | redis | postgres
    url: str = ""


@dataclass
class ToolIndexResource:
    """Runtime semantic tool index settings."""
    search_url: str = ""
    collections: list[str] = field(default_factory=list)
    owner_scope: str = ""


@dataclass
class ResourcesConfig:
    """Runtime infrastructure resources used by the agent."""
    checkpointer: CheckpointerResource = field(default_factory=CheckpointerResource)
    tool_index: ToolIndexResource = field(default_factory=ToolIndexResource)


@dataclass
class AgentConfig:
    """Parsed agent configuration used by the workflow engine."""
    name: str
    prompts: dict[str, str]
    llm: LlmConfig
    mcp: McpConfig
    policy: AgentPolicy
    prompts_inline: dict[str, str] = field(default_factory=dict)
    resources: ResourcesConfig = field(default_factory=ResourcesConfig)
    base_dir: Path = field(default_factory=Path.cwd)

    def prompt_text(self, role: str) -> str:
        """Prompt text."""
        inline = str(self.prompts_inline.get(role) or "").strip()
        if inline:
            return inline
        path = self.prompts.get(role, "")
        if not path:
            return ""
        prompt_path = self.base_dir / path
        if prompt_path.is_file():
            return prompt_path.read_text(encoding="utf-8")
        return path

    def signature(self) -> str:
        """Return a stable cache key for this config without exposing secrets."""
        policy = self.policy
        payload = {
            "name": self.name,
            "prompts": dict(self.prompts),
            "prompts_inline": dict(self.prompts_inline),
            "llm": {
                "base_url": self.llm.base_url,
                "model": self.llm.model,
                "send_auth_header": self.llm.send_auth_header,
                "default_max_tokens": self.llm.default_max_tokens,
                "temperature": self.llm.temperature,
                "top_p": self.llm.top_p,
                "top_k": self.llm.top_k,
                "seed": self.llm.seed,
                "native_tool_calling": self.llm.native_tool_calling,
                "api_key_hash": hashlib.sha256((self.llm.api_key or "").encode("utf-8")).hexdigest(),
            },
            "resources": {
                "checkpointer_mode": self.resources.checkpointer.mode,
                # Connection URLs may embed credentials; hash them.
                "checkpointer_url_hash": hashlib.sha256((self.resources.checkpointer.url or "").encode("utf-8")).hexdigest(),
                "tool_index_search_url": self.resources.tool_index.search_url,
                "tool_index_collections": list(self.resources.tool_index.collections),
                "tool_index_owner_scope": self.resources.tool_index.owner_scope,
            },
            "mcp": {
                "url": self.mcp.url,
                "timeout_seconds": self.mcp.timeout_seconds,
                "verify_ssl": self.mcp.verify_ssl,
                "auth_token_hash": hashlib.sha256((self.mcp.auth_token or "").encode("utf-8")).hexdigest(),
                "servers": [
                    {
                        "name": server.name,
                        "url": server.url,
                        "timeout_seconds": server.timeout_seconds,
                        "verify_ssl": server.verify_ssl,
                        "auth_token_hash": hashlib.sha256((server.auth_token or "").encode("utf-8")).hexdigest(),
                    }
                    for server in self.mcp.servers
                ],
            },
            "policy": {
                "max_executor_iterations": policy.max_executor_iterations,
                "max_review_cycles": policy.max_review_cycles,
                "max_tool_calls_per_step": policy.max_tool_calls_per_step,
                "max_context_tokens": policy.max_context_tokens,
                "llm_timeout_seconds": policy.llm_timeout_seconds,
                "tool_timeout_seconds": policy.tool_timeout_seconds,
                "max_retained_artifacts": policy.max_retained_artifacts,
                "max_retained_tool_calls": policy.max_retained_tool_calls,
                "max_retained_events": policy.max_retained_events,
                "tool_discovery_cache_size": policy.tool_discovery_cache_size,
                "reject_action": policy.reject_action,
                "destructive_tools": list(policy.destructive_tools),
                "require_destructive_confirmation": policy.require_destructive_confirmation,
                "enable_fast_path": policy.enable_fast_path,
                "render_final_answer": policy.render_final_answer,
                "enforce_grounding": policy.enforce_grounding,
                "enable_planner": policy.enable_planner,
                "enable_reviewer": policy.enable_reviewer,
                "cross_turn_artifact_persistence": policy.cross_turn_artifact_persistence,
                "artifact_store_ttl_seconds": policy.artifact_store_ttl_seconds,
                "require_tool_on_follow_up": policy.require_tool_on_follow_up,
                "truncation": {
                    "max_artifact_chars": policy.truncation.max_artifact_chars,
                    "max_string_field_chars": policy.truncation.max_string_field_chars,
                    "max_list_rows_visible": policy.truncation.max_list_rows_visible,
                    "dict_list_budget_reserve": policy.truncation.dict_list_budget_reserve,
                    "dict_list_min_budget": policy.truncation.dict_list_min_budget,
                    "score_weights": dict(policy.truncation.score_weights),
                    "freshness_half_life_seconds": policy.truncation.freshness_half_life_seconds,
                },
                "tools": {
                    "allowlist": list(policy.tools.allowlist),
                    "denylist": list(policy.tools.denylist),
                    "required_tools": dict(policy.tools.required_tools),
                    "argument_injection": dict(policy.tools.argument_injection),
                },
                "planner": {
                    "enabled": policy.planner.enabled,
                    "max_tokens": policy.planner.max_tokens,
                },
                "reviewer": {
                    "enabled": policy.reviewer.enabled,
                    "max_tokens": policy.reviewer.max_tokens,
                    "max_cycles": policy.reviewer.max_cycles,
                    "reject_action": policy.reviewer.reject_action,
                    "mode": policy.reviewer.mode,
                },
                "executor": {
                    "choose_action_max_tokens": policy.executor.choose_action_max_tokens,
                    "native_tool_max_tokens": policy.executor.native_tool_max_tokens,
                    "synthesize_max_tokens": policy.executor.synthesize_max_tokens,
                    "max_native_tools": policy.executor.max_native_tools,
                    "tool_description_max_chars": policy.executor.tool_description_max_chars,
                    "fallback_artifact_limit": policy.executor.fallback_artifact_limit,
                    "mechanical_artifact_limit": policy.executor.mechanical_artifact_limit,
                    "mechanical_line_limit": policy.executor.mechanical_line_limit,
                    "fallback_summary_chars": policy.executor.fallback_summary_chars,
                },
                "finalizer": {
                    "max_tokens": policy.finalizer.max_tokens,
                    "max_artifact_lines": policy.finalizer.max_artifact_lines,
                    "artifact_line_max_chars": policy.finalizer.artifact_line_max_chars,
                },
                "router": {
                    "fast_path_max_tokens": policy.router.fast_path_max_tokens,
                    "fast_path_max_query_chars": policy.router.fast_path_max_query_chars,
                    "fast_path_max_query_words": policy.router.fast_path_max_query_words,
                    "fast_path_history_messages": policy.router.fast_path_history_messages,
                    "fast_path_history_content_chars": policy.router.fast_path_history_content_chars,
                    "merge_state_max_events": policy.router.merge_state_max_events,
                },
                "context": {
                    "system_budget_padding": policy.context.system_budget_padding,
                    "min_artifact_budget_tokens": policy.context.min_artifact_budget_tokens,
                    "trim_section_min_chars": policy.context.trim_section_min_chars,
                    "max_tools_in_prompt": policy.context.max_tools_in_prompt,
                    "max_tool_calls_in_prompt": policy.context.max_tool_calls_in_prompt,
                    "max_artifacts_in_prompt": policy.context.max_artifacts_in_prompt,
                    "max_history_messages": policy.context.max_history_messages,
                    "history_preview_head_chars": policy.context.history_preview_head_chars,
                    "history_preview_tail_chars": policy.context.history_preview_tail_chars,
                    "artifact_summary_ratio": policy.context.artifact_summary_ratio,
                    "artifact_summary_min_chars": policy.context.artifact_summary_min_chars,
                },
                "model": policy.model,
                "instructions": policy.instructions,
            },
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()



def _transport_timeout(deadline_seconds: float, *, margin_seconds: float = 1.0) -> float:
    """Helper for transport timeout."""
    if deadline_seconds <= margin_seconds:
        return max(0.1, deadline_seconds * 0.8)
    return max(0.1, deadline_seconds - margin_seconds)

def _default_score_weights() -> dict[str, float]:
    """Helper for default score weights."""
    return {
        "relevance": 0.4,
        "freshness": 0.2,
        "uniqueness": 0.2,
        "actionability": 0.2,
    }


def parse_agent_config(raw: dict[str, Any], *, base_dir: Path | None = None) -> AgentConfig:
    """Validate raw config data and convert it into runtime dataclasses."""
    resolved = _resolve_env_deep(deepcopy(raw or {}))
    model = AgentConfigModel.model_validate(resolved)
    policy_raw = model.policy
    trunc_raw = policy_raw.truncation

    planner_enabled = _as_bool(policy_raw.planner.enabled, _as_bool(policy_raw.enable_planner, True))
    reviewer_enabled = _as_bool(policy_raw.reviewer.enabled, _as_bool(policy_raw.enable_reviewer, True))
    review_max_cycles = _as_int(policy_raw.reviewer.max_cycles, _as_int(policy_raw.max_review_cycles, 2))
    reject_action = str(policy_raw.reviewer.reject_action or policy_raw.reject_action or "replan")

    policy = AgentPolicy(
        max_executor_iterations=_as_int(policy_raw.max_executor_iterations, 12),
        max_review_cycles=review_max_cycles,
        max_tool_calls_per_step=_as_int(policy_raw.max_tool_calls_per_step, 4),
        max_context_tokens=_as_int(policy_raw.max_context_tokens, 12000),
        llm_timeout_seconds=_as_float(policy_raw.llm_timeout_seconds, 60.0),
        tool_timeout_seconds=_as_float(policy_raw.tool_timeout_seconds, 120.0),
        max_retained_artifacts=_as_int(policy_raw.max_retained_artifacts, 24),
        max_retained_tool_calls=_as_int(policy_raw.max_retained_tool_calls, 40),
        max_retained_events=_as_int(policy_raw.max_retained_events, 80),
        tool_discovery_cache_size=_as_int(policy_raw.tool_discovery_cache_size, 16),
        reject_action=reject_action,
        destructive_tools=list(policy_raw.destructive_tools or []),
        require_destructive_confirmation=_as_bool(policy_raw.require_destructive_confirmation, True),
        enable_fast_path=_as_bool(policy_raw.enable_fast_path, True),
        render_final_answer=_as_bool(policy_raw.render_final_answer, True),
        enforce_grounding=_as_bool(policy_raw.enforce_grounding, False),
        enable_planner=planner_enabled,
        enable_reviewer=reviewer_enabled,
        cross_turn_artifact_persistence=_as_bool(policy_raw.cross_turn_artifact_persistence, False),
        artifact_store_ttl_seconds=_as_int(policy_raw.artifact_store_ttl_seconds, 86400),
        require_tool_on_follow_up=_as_bool(policy_raw.require_tool_on_follow_up, True),
        truncation=TruncationPolicy(
            max_artifact_chars=_as_int(trunc_raw.max_artifact_chars, 2500),
            max_string_field_chars=_as_int(trunc_raw.max_string_field_chars, 400),
            max_list_rows_visible=_as_int(trunc_raw.max_list_rows_visible, 100),
            dict_list_budget_reserve=_as_int(trunc_raw.dict_list_budget_reserve, 96),
            dict_list_min_budget=_as_int(trunc_raw.dict_list_min_budget, 200),
            score_weights=dict(trunc_raw.score_weights or _default_score_weights()),
            freshness_half_life_seconds=_as_float(trunc_raw.freshness_half_life_seconds, 3600.0),
        ),
        tools=ToolPolicy(
            allowlist=list(policy_raw.tools.allowlist or []),
            denylist=list(policy_raw.tools.denylist or []),
            required_tools={str(k): list(v or []) for k, v in (policy_raw.tools.required_tools or {}).items()},
            argument_injection={
                str(tool): {str(arg): str(path) for arg, path in mapping.items()}
                for tool, mapping in (policy_raw.tools.argument_injection or {}).items()
            },
        ),
        planner=PlannerDefaults(
            enabled=planner_enabled,
            max_tokens=_as_int(policy_raw.planner.max_tokens, 1500),
        ),
        reviewer=ReviewerDefaults(
            enabled=reviewer_enabled,
            max_tokens=_as_int(policy_raw.reviewer.max_tokens, 2400),
            max_cycles=review_max_cycles,
            reject_action=reject_action,
            mode=str(policy_raw.reviewer.mode or "always"),
        ),
        executor=ExecutorDefaults(
            choose_action_max_tokens=_as_int(policy_raw.executor.choose_action_max_tokens, 1200),
            native_tool_max_tokens=_as_int(policy_raw.executor.native_tool_max_tokens, 1200),
            synthesize_max_tokens=_as_int(policy_raw.executor.synthesize_max_tokens, 2000),
            max_native_tools=_as_int(policy_raw.executor.max_native_tools, 7),
            tool_description_max_chars=_as_int(policy_raw.executor.tool_description_max_chars, 1024),
            fallback_artifact_limit=_as_int(policy_raw.executor.fallback_artifact_limit, 5),
            mechanical_artifact_limit=_as_int(policy_raw.executor.mechanical_artifact_limit, 12),
            mechanical_line_limit=_as_int(policy_raw.executor.mechanical_line_limit, 120),
            fallback_summary_chars=_as_int(policy_raw.executor.fallback_summary_chars, 400),
        ),
        finalizer=FinalizerDefaults(
            max_tokens=_as_int(policy_raw.finalizer.max_tokens, 2000),
            max_artifact_lines=_as_int(policy_raw.finalizer.max_artifact_lines, 12),
            artifact_line_max_chars=_as_int(policy_raw.finalizer.artifact_line_max_chars, 1200),
        ),
        router=RouterDefaults(
            fast_path_max_tokens=_as_int(policy_raw.router.fast_path_max_tokens, 512),
            fast_path_max_query_chars=_as_int(policy_raw.router.fast_path_max_query_chars, 180),
            fast_path_max_query_words=_as_int(policy_raw.router.fast_path_max_query_words, 24),
            fast_path_history_messages=_as_int(policy_raw.router.fast_path_history_messages, 4),
            fast_path_history_content_chars=_as_int(policy_raw.router.fast_path_history_content_chars, 1000),
            merge_state_max_events=_as_int(policy_raw.router.merge_state_max_events, 80),
        ),
        context=ContextLimits(
            system_budget_padding=_as_int(policy_raw.context.system_budget_padding, 50),
            min_artifact_budget_tokens=_as_int(policy_raw.context.min_artifact_budget_tokens, 200),
            trim_section_min_chars=_as_int(policy_raw.context.trim_section_min_chars, 200),
            max_tools_in_prompt=_as_int(policy_raw.context.max_tools_in_prompt, 7),
            max_tool_calls_in_prompt=_as_int(policy_raw.context.max_tool_calls_in_prompt, 5),
            max_artifacts_in_prompt=_as_int(policy_raw.context.max_artifacts_in_prompt, 10),
            max_history_messages=_as_int(policy_raw.context.max_history_messages, 6),
            history_preview_head_chars=_as_int(policy_raw.context.history_preview_head_chars, 400),
            history_preview_tail_chars=_as_int(policy_raw.context.history_preview_tail_chars, 400),
            artifact_summary_ratio=_as_float(policy_raw.context.artifact_summary_ratio, 0.75),
            artifact_summary_min_chars=_as_int(policy_raw.context.artifact_summary_min_chars, 1200),
        ),
        model=policy_raw.model,
        instructions=str(policy_raw.instructions or ""),
    )

    llm_raw = model.llm
    tool_transport_timeout = _transport_timeout(policy.tool_timeout_seconds)

    llm = LlmConfig(
        base_url=str(llm_raw.base_url).strip(),
        api_key=str(llm_raw.api_key).strip(),
        model=str(llm_raw.model).strip(),
        send_auth_header=_as_bool(llm_raw.send_auth_header, True),
        default_max_tokens=_as_int(llm_raw.default_max_tokens, 1024),
        temperature=_as_float(llm_raw.temperature, 0.2),
        top_p=_as_float(llm_raw.top_p, 0.9),
        top_k=_as_int(llm_raw.top_k, 40),
        seed=_as_int(llm_raw.seed, 0xFFFFFFFF),
        native_tool_calling=_as_bool(llm_raw.native_tool_calling, False),
    )

    resources_raw = model.resources
    resources = ResourcesConfig(
        checkpointer=CheckpointerResource(
            mode=str(resources_raw.checkpointer.mode or "").strip().lower(),
            url=str(resources_raw.checkpointer.url or "").strip(),
        ),
        tool_index=ToolIndexResource(
            search_url=str(resources_raw.tool_index.search_url or "").strip(),
            collections=[str(item).strip() for item in (resources_raw.tool_index.collections or []) if str(item).strip()],
            owner_scope=str(resources_raw.tool_index.owner_scope or "").strip(),
        ),
    )

    mcp_raw = model.mcp
    servers = [
        McpServerConfig(
            name=str(entry.name).strip() or f"server{idx + 1}",
            url=str(entry.url or "").strip(),
            auth_token=str(entry.auth_token or "").strip(),
            timeout_seconds=min(_as_float(entry.timeout_seconds, _as_float(mcp_raw.timeout_seconds, tool_transport_timeout)), tool_transport_timeout),
            verify_ssl=_as_bool(entry.verify_ssl, _as_bool(mcp_raw.verify_ssl, True)),
            proxy_url=str(getattr(entry, "proxy_url", "") or "").strip(),
            tool_discovery=ToolDiscoveryConfig(
                mode=str(entry.tool_discovery.mode or "fallback"),
                search_url=str(entry.tool_discovery.search_url or "").strip(),
                collections=[str(item).strip() for item in (entry.tool_discovery.collections or []) if str(item).strip()],
                owner_scope=str(entry.tool_discovery.owner_scope or "").strip(),
                indexed=_as_bool(entry.tool_discovery.indexed, False),
            ),
        )
        for idx, entry in enumerate(mcp_raw.servers or [])
    ]

    # A shared tool-index resource is the default semantic tool-search endpoint
    # for every server that does not configure its own.
    if resources.tool_index.search_url:
        for server in servers:
            if not server.tool_discovery.search_url:
                server.tool_discovery.search_url = resources.tool_index.search_url
                if not server.tool_discovery.collections:
                    server.tool_discovery.collections = list(resources.tool_index.collections)
                if not server.tool_discovery.owner_scope:
                    server.tool_discovery.owner_scope = resources.tool_index.owner_scope

    mcp = McpConfig(
        url=str(mcp_raw.url or os.getenv("MCP_URL", "")).strip(),
        auth_token=str(mcp_raw.auth_token or os.getenv("MCP_AUTH_TOKEN", "")).strip(),
        timeout_seconds=min(_as_float(mcp_raw.timeout_seconds, tool_transport_timeout), tool_transport_timeout),
        verify_ssl=_as_bool(mcp_raw.verify_ssl, True),
        servers=servers,
    )

    resolved_base_dir = (base_dir or Path.cwd()).resolve()
    return AgentConfig(
        name=str(model.name or "agent"),
        prompts=dict(model.prompts or {}),
        prompts_inline={k: str(v) for k, v in (model.prompts_inline or {}).items()},
        llm=llm,
        mcp=mcp,
        policy=policy,
        resources=resources,
        base_dir=resolved_base_dir,
    )


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Helper for deep merge."""
    merged = deepcopy(base)
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(dict(merged[key]), value)
        else:
            merged[key] = deepcopy(value)
    return merged


def merge_agent_config(base: AgentConfig, overrides: dict[str, Any]) -> AgentConfig:
    """Apply runtime overrides to an existing agent config."""
    base_raw = {
        "name": base.name,
        "prompts": dict(base.prompts),
        "prompts_inline": dict(base.prompts_inline),
        "llm": {
            "base_url": base.llm.base_url,
            "api_key": base.llm.api_key,
            "model": base.llm.model,
            "send_auth_header": base.llm.send_auth_header,
            "default_max_tokens": base.llm.default_max_tokens,
            "temperature": base.llm.temperature,
            "top_p": base.llm.top_p,
            "top_k": base.llm.top_k,
            "seed": base.llm.seed,
            "native_tool_calling": base.llm.native_tool_calling,
        },
        "resources": {
            "checkpointer": {
                "mode": base.resources.checkpointer.mode,
                "url": base.resources.checkpointer.url,
            },
            "tool_index": {
                "search_url": base.resources.tool_index.search_url,
                "collections": list(base.resources.tool_index.collections),
                "owner_scope": base.resources.tool_index.owner_scope,
            },
        },
        "mcp": {
            "url": base.mcp.url,
            "auth_token": base.mcp.auth_token,
            "timeout_seconds": base.mcp.timeout_seconds,
            "verify_ssl": base.mcp.verify_ssl,
            "servers": [
                {
                    "name": server.name,
                    "url": server.url,
                    "auth_token": server.auth_token,
                    "timeout_seconds": server.timeout_seconds,
                    "verify_ssl": server.verify_ssl,
                    "proxy_url": server.proxy_url,
                    "tool_discovery": {
                        "mode": server.tool_discovery.mode,
                        "search_url": server.tool_discovery.search_url,
                        "collections": list(server.tool_discovery.collections),
                        "owner_scope": server.tool_discovery.owner_scope,
                        "indexed": server.tool_discovery.indexed,
                    },
                }
                for server in base.mcp.servers
            ],
        },
        "policy": {
            "max_executor_iterations": base.policy.max_executor_iterations,
            "max_review_cycles": base.policy.max_review_cycles,
            "max_tool_calls_per_step": base.policy.max_tool_calls_per_step,
            "max_context_tokens": base.policy.max_context_tokens,
            "llm_timeout_seconds": base.policy.llm_timeout_seconds,
            "tool_timeout_seconds": base.policy.tool_timeout_seconds,
            "max_retained_artifacts": base.policy.max_retained_artifacts,
            "max_retained_tool_calls": base.policy.max_retained_tool_calls,
            "max_retained_events": base.policy.max_retained_events,
            "tool_discovery_cache_size": base.policy.tool_discovery_cache_size,
            "reject_action": base.policy.reject_action,
            "destructive_tools": list(base.policy.destructive_tools),
            "require_destructive_confirmation": base.policy.require_destructive_confirmation,
            "enable_fast_path": base.policy.enable_fast_path,
            "render_final_answer": base.policy.render_final_answer,
            "enforce_grounding": base.policy.enforce_grounding,
            "enable_planner": base.policy.enable_planner,
            "enable_reviewer": base.policy.enable_reviewer,
            "cross_turn_artifact_persistence": base.policy.cross_turn_artifact_persistence,
            "artifact_store_ttl_seconds": base.policy.artifact_store_ttl_seconds,
            "require_tool_on_follow_up": base.policy.require_tool_on_follow_up,
            "truncation": {
                "max_artifact_chars": base.policy.truncation.max_artifact_chars,
                "max_string_field_chars": base.policy.truncation.max_string_field_chars,
                "max_list_rows_visible": base.policy.truncation.max_list_rows_visible,
                "dict_list_budget_reserve": base.policy.truncation.dict_list_budget_reserve,
                "dict_list_min_budget": base.policy.truncation.dict_list_min_budget,
                "score_weights": dict(base.policy.truncation.score_weights),
                "freshness_half_life_seconds": base.policy.truncation.freshness_half_life_seconds,
            },
            "tools": {
                "allowlist": list(base.policy.tools.allowlist),
                "denylist": list(base.policy.tools.denylist),
                "required_tools": dict(base.policy.tools.required_tools),
                "argument_injection": dict(base.policy.tools.argument_injection),
            },
            "planner": {
                "enabled": base.policy.planner.enabled,
                "max_tokens": base.policy.planner.max_tokens,
            },
            "reviewer": {
                "enabled": base.policy.reviewer.enabled,
                "max_tokens": base.policy.reviewer.max_tokens,
                "max_cycles": base.policy.reviewer.max_cycles,
                "reject_action": base.policy.reviewer.reject_action,
                "mode": base.policy.reviewer.mode,
            },
            "executor": {
                "choose_action_max_tokens": base.policy.executor.choose_action_max_tokens,
                "native_tool_max_tokens": base.policy.executor.native_tool_max_tokens,
                "synthesize_max_tokens": base.policy.executor.synthesize_max_tokens,
                "max_native_tools": base.policy.executor.max_native_tools,
                "tool_description_max_chars": base.policy.executor.tool_description_max_chars,
                "fallback_artifact_limit": base.policy.executor.fallback_artifact_limit,
                "mechanical_artifact_limit": base.policy.executor.mechanical_artifact_limit,
                "mechanical_line_limit": base.policy.executor.mechanical_line_limit,
                "fallback_summary_chars": base.policy.executor.fallback_summary_chars,
            },
            "finalizer": {
                "max_tokens": base.policy.finalizer.max_tokens,
                "max_artifact_lines": base.policy.finalizer.max_artifact_lines,
                "artifact_line_max_chars": base.policy.finalizer.artifact_line_max_chars,
            },
            "router": {
                "fast_path_max_tokens": base.policy.router.fast_path_max_tokens,
                "fast_path_max_query_chars": base.policy.router.fast_path_max_query_chars,
                "fast_path_max_query_words": base.policy.router.fast_path_max_query_words,
                "fast_path_history_messages": base.policy.router.fast_path_history_messages,
                "fast_path_history_content_chars": base.policy.router.fast_path_history_content_chars,
                "merge_state_max_events": base.policy.router.merge_state_max_events,
            },
            "context": {
                "system_budget_padding": base.policy.context.system_budget_padding,
                "min_artifact_budget_tokens": base.policy.context.min_artifact_budget_tokens,
                "trim_section_min_chars": base.policy.context.trim_section_min_chars,
                "max_tools_in_prompt": base.policy.context.max_tools_in_prompt,
                "max_tool_calls_in_prompt": base.policy.context.max_tool_calls_in_prompt,
                "max_artifacts_in_prompt": base.policy.context.max_artifacts_in_prompt,
                "max_history_messages": base.policy.context.max_history_messages,
                "history_preview_head_chars": base.policy.context.history_preview_head_chars,
                "history_preview_tail_chars": base.policy.context.history_preview_tail_chars,
                "artifact_summary_ratio": base.policy.context.artifact_summary_ratio,
                "artifact_summary_min_chars": base.policy.context.artifact_summary_min_chars,
            },
            "model": base.policy.model,
            "instructions": base.policy.instructions,
        },
    }
    merged_raw = _deep_merge(base_raw, overrides or {})
    return parse_agent_config(merged_raw, base_dir=base.base_dir)


def load_agent_config(path: str | Path) -> AgentConfig:
    """Load YAML or JSON config from disk and parse it."""
    config_path = Path(path).resolve()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    base_dir = config_path.parent
    if not (base_dir / "prompts").exists() and (config_path.parent.parent / "prompts").exists():
        base_dir = config_path.parent.parent
    return parse_agent_config(raw, base_dir=base_dir)
