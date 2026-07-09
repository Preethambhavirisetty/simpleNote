from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

from fastapi import HTTPException

from app.agent_workflow.engine import AgentEngine
from app.agent_workflow.exploration_profile import (
    apply_exploration_profile_to_overrides,
    resolve_exploration_profile,
    validate_runtime_context_profile,
)
from app.api.checkpointer import get_runtime_checkpointer
from app.agent_workflow.streaming import RunRequest
from app.api.config import AGENT_CONFIG_DIR, ALLOWED_UPSTREAM_HOSTS, DEFAULT_EXPLORATION_PROFILE
from app.api.schema import AgentWorkflowRunRequest, AgentWorkflowRuntimeBundleRequest
from app.api.runtime_bundle_adapter import build_runtime_overrides
from app.api.sse_adapter import engine_event_to_sse, sse_encode


_BUILTIN_CONFIG_DIR = Path(__file__).resolve().parents[1] / "agent_workflow" / "agents"
_ALLOWED_CONFIG_DIR = Path(AGENT_CONFIG_DIR).resolve() if AGENT_CONFIG_DIR else _BUILTIN_CONFIG_DIR.resolve()
_DEFAULT_CONFIG_PATH = _ALLOWED_CONFIG_DIR / "default.yaml"



# ---------------- helper functions ----------------

def _host_from_url(value: Any) -> str:
    """
    Get the host from the provided URL.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    return (parsed.hostname or "").lower()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _resolve_config_path(config_name: str | None, config_path: str | None) -> Path:
    """
    Resolve the configuration path based on the provided config_name or config_path.
    """
    if config_name and config_path:
        raise HTTPException(status_code=400, detail="Use config_name or config_path, not both")
    if config_name:
        candidate = _ALLOWED_CONFIG_DIR / config_name
        if candidate.suffix not in {".yaml", ".yml", ".json"}:
            candidate = candidate.with_suffix(".yaml")
    elif config_path:
        requested = Path(config_path)
        candidate = requested if requested.is_absolute() else _ALLOWED_CONFIG_DIR / requested
    else:
        candidate = _DEFAULT_CONFIG_PATH

    resolved = candidate.resolve()
    if not _is_relative_to(resolved, _ALLOWED_CONFIG_DIR):
        raise HTTPException(status_code=400, detail="Config path is outside the allowed config directory")
    if not resolved.is_file():
        raise HTTPException(status_code=400, detail=f"Config not found: {resolved.name}")
    return resolved


def _validate_outbound_hosts(config: dict[str, Any]) -> None:
    """
    Validate the outbound hosts based on the provided configuration.
    """
    hosts = [host for host in _iter_upstream_hosts(config) if host]
    denied = sorted({host for host in hosts if host not in ALLOWED_UPSTREAM_HOSTS})
    if denied:
        allowed = ", ".join(sorted(ALLOWED_UPSTREAM_HOSTS)) or "<none>"
        raise HTTPException(
            status_code=400,
            detail=f"Outbound upstream host is not allowed: {', '.join(denied)}. Allowed hosts: {allowed}",
        )


def _iter_upstream_hosts(config: dict[str, Any]) -> Iterator[str]:
    """
    Iterate over the upstream hosts based on the provided configuration.
    """
    llm = config.get("llm") if isinstance(config.get("llm"), dict) else {}
    host = _host_from_url(llm.get("base_url"))
    if host:
        yield host

    resources = config.get("resources") if isinstance(config.get("resources"), dict) else {}
    checkpointer = resources.get("checkpointer") if isinstance(resources.get("checkpointer"), dict) else {}
    host = _host_from_url(checkpointer.get("url"))
    if host:
        yield host
    tool_index = resources.get("tool_index") if isinstance(resources.get("tool_index"), dict) else {}
    host = _host_from_url(tool_index.get("search_url"))
    if host:
        yield host

    mcp = config.get("mcp") if isinstance(config.get("mcp"), dict) else {}
    host = _host_from_url(mcp.get("url"))
    if host:
        yield host
    for server in mcp.get("servers") or []:
        if not isinstance(server, dict):
            continue
        host = _host_from_url(server.get("url"))
        if host:
            yield host
        discovery = server.get("tool_discovery") if isinstance(server.get("tool_discovery"), dict) else {}
        host = _host_from_url(discovery.get("search_url"))
        if host:
            yield host


def _validate_exploration_profile(runtime_context: dict[str, Any]) -> None:
    """Reject an invalid exploration_profile with a clear 400 instead of silently defaulting."""
    try:
        validate_runtime_context_profile(runtime_context)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def build_run_request(payload: AgentWorkflowRunRequest | AgentWorkflowRuntimeBundleRequest) -> RunRequest:
    return RunRequest(
        query=payload.query,
        session_id=payload.session_id,
        history=[message.model_dump(mode="json") for message in payload.history],
        runtime_context=dict(payload.runtime_context or {}),
    )


# ---------------- main functions ----------------

def resolve_engine(payload: AgentWorkflowRunRequest) -> AgentEngine:
    """
    sample payload:
    {
        "config": {
            "name": "default",
            "path": "default.yaml",
            "runtime_overrides": {
                "name": "default",
            }
        }
    }
    """
    runtime_context = dict(payload.runtime_context or {})
    _validate_exploration_profile(runtime_context)
    if payload.config is not None:
        _validate_outbound_hosts(payload.config)
        if payload.runtime_overrides:
            overrides = dict(payload.runtime_overrides)
            _validate_outbound_hosts(overrides)
            apply_exploration_profile_to_overrides(
                overrides,
                runtime_context,
                env_default=DEFAULT_EXPLORATION_PROFILE,
            )
            return AgentEngine.from_runtime_config(payload.config, overrides, checkpointer=get_runtime_checkpointer())
        merged = dict(payload.config)
        apply_exploration_profile_to_overrides(
            merged,
            runtime_context,
            env_default=DEFAULT_EXPLORATION_PROFILE,
        )
        return AgentEngine.from_dict(merged, checkpointer=get_runtime_checkpointer())

    config_path = _resolve_config_path(payload.config_name, payload.config_path)
    if payload.runtime_overrides:
        overrides = dict(payload.runtime_overrides)
        _validate_outbound_hosts(overrides)
        apply_exploration_profile_to_overrides(
            overrides,
            runtime_context,
            env_default=DEFAULT_EXPLORATION_PROFILE,
        )
        return AgentEngine.from_runtime_config(config_path, overrides, checkpointer=get_runtime_checkpointer())
    overrides: dict[str, Any] = {}
    apply_exploration_profile_to_overrides(
        overrides,
        runtime_context,
        env_default=DEFAULT_EXPLORATION_PROFILE,
    )
    if overrides:
        return AgentEngine.from_runtime_config(config_path, overrides, checkpointer=get_runtime_checkpointer())
    return AgentEngine.from_config(config_path, checkpointer=get_runtime_checkpointer())


def resolve_engine_from_runtime_bundle(payload: AgentWorkflowRuntimeBundleRequest) -> AgentEngine:
    runtime_context = dict(payload.runtime_context or {})
    _validate_exploration_profile(runtime_context)
    # build_runtime_overrides already applies the resolved exploration profile,
    # so the bundle path honors quick/heavy mode without a second application.
    overrides = build_runtime_overrides(payload.runtime_bundle, runtime_context=runtime_context)
    _validate_outbound_hosts(overrides)
    return AgentEngine.from_runtime_config(_DEFAULT_CONFIG_PATH, overrides, checkpointer=get_runtime_checkpointer())


def stream_sse(payload: AgentWorkflowRunRequest) -> Iterator[str]:
    runtime_context = dict(payload.runtime_context or {})
    engine = resolve_engine(payload)
    request = build_run_request(payload)
    profile = resolve_exploration_profile(runtime_context, env_default=DEFAULT_EXPLORATION_PROFILE)
    yield sse_encode(
        "meta",
        {
            "session_id": request.session_id,
            "config_name": engine.config.name,
            "engine": "agent_workflow",
            "exploration_profile": profile,
        },
    )
    for event in engine.stream(request):
        mapped = engine_event_to_sse(event)
        if mapped is None:
            continue
        event_name, data = mapped
        yield sse_encode(event_name, data)


def stream_sse_runtime_bundle(payload: AgentWorkflowRuntimeBundleRequest) -> Iterator[str]:
    runtime_context = dict(payload.runtime_context or {})
    engine = resolve_engine_from_runtime_bundle(payload)
    request = build_run_request(payload)
    profile = resolve_exploration_profile(runtime_context, env_default=DEFAULT_EXPLORATION_PROFILE)
    yield sse_encode(
        "meta",
        {
            "session_id": request.session_id,
            "config_name": engine.config.name,
            "engine": "agent_workflow",
            "source": "runtime_bundle",
            "exploration_profile": profile,
        },
    )
    for event in engine.stream(request):
        mapped = engine_event_to_sse(event)
        if mapped is None:
            continue
        event_name, data = mapped
        yield sse_encode(event_name, data)
