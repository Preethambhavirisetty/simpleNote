from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


_ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _resolve_env(value: str) -> str:
    def replacer(match: re.Match[str]) -> str:
        key = match.group(1)
        return os.getenv(key, "")

    return _ENV_PATTERN.sub(replacer, value)


def _resolve_env_deep(obj: Any) -> Any:
    if isinstance(obj, str):
        return _resolve_env(obj)
    if isinstance(obj, dict):
        return {k: _resolve_env_deep(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_deep(v) for v in obj]
    return obj


@dataclass
class TruncationPolicy:
    max_artifact_chars: int = 2500
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
class AgentPolicy:
    max_executor_iterations: int = 12
    max_review_cycles: int = 2
    max_tool_calls_per_step: int = 4
    max_context_tokens: int = 12000
    reject_action: str = "replan"  # replan | abort
    destructive_tools: list[str] = field(default_factory=list)
    require_destructive_confirmation: bool = True
    truncation: TruncationPolicy = field(default_factory=TruncationPolicy)
    model: str | None = None
    instructions: str = ""


@dataclass
class McpConfig:
    url: str = ""
    auth_token: str = ""
    timeout_seconds: float = 120.0
    verify_ssl: bool = True


@dataclass
class AgentConfig:
    name: str
    prompts: dict[str, str]
    mcp: McpConfig
    policy: AgentPolicy
    base_dir: Path = field(default_factory=Path.cwd)

    def prompt_text(self, role: str) -> str:
        path = self.prompts.get(role, "")
        if not path:
            return ""
        prompt_path = self.base_dir / path
        if prompt_path.is_file():
            return prompt_path.read_text(encoding="utf-8")
        return path


def load_agent_config(path: str | Path) -> AgentConfig:
    config_path = Path(path).resolve()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    raw = _resolve_env_deep(raw)

    policy_raw = raw.get("policy") or {}
    trunc_raw = policy_raw.get("truncation") or {}

    policy = AgentPolicy(
        max_executor_iterations=int(policy_raw.get("max_executor_iterations", 12)),
        max_review_cycles=int(policy_raw.get("max_review_cycles", 2)),
        max_tool_calls_per_step=int(policy_raw.get("max_tool_calls_per_step", 4)),
        max_context_tokens=int(policy_raw.get("max_context_tokens", 12000)),
        reject_action=str(policy_raw.get("reject_action", "replan")),
        destructive_tools=list(policy_raw.get("destructive_tools") or []),
        require_destructive_confirmation=bool(
            policy_raw.get("require_destructive_confirmation", True)
        ),
        truncation=TruncationPolicy(
            max_artifact_chars=int(trunc_raw.get("max_artifact_chars", 2500)),
            score_weights=dict(
                trunc_raw.get("score_weights")
                or {
                    "relevance": 0.4,
                    "freshness": 0.2,
                    "uniqueness": 0.2,
                    "actionability": 0.2,
                }
            ),
            freshness_half_life_seconds=float(
                trunc_raw.get("freshness_half_life_seconds", 3600.0)
            ),
        ),
        model=policy_raw.get("model"),
        instructions=str(policy_raw.get("instructions", "")),
    )

    mcp_raw = raw.get("mcp") or {}
    mcp = McpConfig(
        url=str(mcp_raw.get("url") or os.getenv("MCP_URL", "")).strip(),
        auth_token=str(mcp_raw.get("auth_token") or os.getenv("MCP_AUTH_TOKEN", "")).strip(),
        timeout_seconds=float(mcp_raw.get("timeout_seconds", 120.0)),
        verify_ssl=bool(mcp_raw.get("verify_ssl", True)),
    )

    base_dir = config_path.parent
    if not (base_dir / "prompts").exists() and (config_path.parent.parent / "prompts").exists():
        base_dir = config_path.parent.parent

    return AgentConfig(
        name=str(raw.get("name", "agent")),
        prompts=dict(raw.get("prompts") or {}),
        mcp=mcp,
        policy=policy,
        base_dir=base_dir,
    )
