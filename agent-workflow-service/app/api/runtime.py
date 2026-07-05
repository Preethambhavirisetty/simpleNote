from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

from fastapi import HTTPException

from app.agent_workflow.engine import AgentEngine
from app.api.checkpointer import get_runtime_checkpointer
from app.agent_workflow.streaming import RunRequest
from app.api.config import AGENT_CONFIG_DIR, ALLOWED_UPSTREAM_HOSTS
from app.api.runtime_bundle_adapter import build_engine_from_runtime_bundle, build_runtime_overrides
from app.api.schema import AgentWorkflowRunRequest, AgentWorkflowRuntimeBundleRequest
from app.api.sse_adapter import engine_event_to_sse, sse_encode


_BUILTIN_CONFIG_DIR = Path(__file__).resolve().parents[1] / "agent_workflow" / "agents"
_ALLOWED_CONFIG_DIR = Path(AGENT_CONFIG_DIR).resolve() if AGENT_CONFIG_DIR else _BUILTIN_CONFIG_DIR.resolve()
_DEFAULT_CONFIG_PATH = _ALLOWED_CONFIG_DIR / "default.yaml"


def resolve_engine(payload: AgentWorkflowRunRequest) -> AgentEngine:
    if payload.config is not None:
        _validate_outbound_hosts(payload.config)
        if payload.runtime_overrides:
            _validate_outbound_hosts(payload.runtime_overrides)
            return AgentEngine.from_runtime_config(payload.config, payload.runtime_overrides, checkpointer=get_runtime_checkpointer())
        return AgentEngine.from_dict(payload.config, checkpointer=get_runtime_checkpointer())

    config_path = _resolve_config_path(payload.config_name, payload.config_path)
    if payload.runtime_overrides:
        _validate_outbound_hosts(payload.runtime_overrides)
        return AgentEngine.from_runtime_config(config_path, payload.runtime_overrides, checkpointer=get_runtime_checkpointer())
    return AgentEngine.from_config(config_path, checkpointer=get_runtime_checkpointer())


def resolve_engine_from_runtime_bundle(payload: AgentWorkflowRuntimeBundleRequest) -> AgentEngine:
    overrides = build_runtime_overrides(payload.runtime_bundle)
    _validate_outbound_hosts(overrides)
    return AgentEngine.from_runtime_config(_DEFAULT_CONFIG_PATH, overrides, checkpointer=get_runtime_checkpointer())


def _resolve_config_path(config_name: str | None, config_path: str | None) -> Path:
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
    hosts = [host for host in _iter_upstream_hosts(config) if host]
    denied = sorted({host for host in hosts if host not in ALLOWED_UPSTREAM_HOSTS})
    if denied:
        allowed = ", ".join(sorted(ALLOWED_UPSTREAM_HOSTS)) or "<none>"
        raise HTTPException(
            status_code=400,
            detail=f"Outbound upstream host is not allowed: {', '.join(denied)}. Allowed hosts: {allowed}",
        )


def _iter_upstream_hosts(config: dict[str, Any]) -> Iterator[str]:
    llm = config.get("llm") if isinstance(config.get("llm"), dict) else {}
    host = _host_from_url(llm.get("base_url"))
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


def _host_from_url(value: Any) -> str:
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


def build_run_request(payload: AgentWorkflowRunRequest | AgentWorkflowRuntimeBundleRequest) -> RunRequest:
    return RunRequest(
        query=payload.query,
        session_id=payload.session_id,
        history=[message.model_dump(mode="json") for message in payload.history],
        runtime_context=dict(payload.runtime_context or {}),
    )


def stream_sse(payload: AgentWorkflowRunRequest) -> Iterator[str]:
    engine = resolve_engine(payload)
    request = build_run_request(payload)
    yield sse_encode(
        "meta",
        {
            "session_id": request.session_id,
            "config_name": engine.config.name,
            "engine": "agent_workflow",
        },
    )
    for event in engine.stream(request):
        mapped = engine_event_to_sse(event)
        if mapped is None:
            continue
        event_name, data = mapped
        yield sse_encode(event_name, data)


def stream_sse_runtime_bundle(payload: AgentWorkflowRuntimeBundleRequest) -> Iterator[str]:
    engine = resolve_engine_from_runtime_bundle(payload)
    request = build_run_request(payload)
    yield sse_encode(
        "meta",
        {
            "session_id": request.session_id,
            "config_name": engine.config.name,
            "engine": "agent_workflow",
            "source": "runtime_bundle",
        },
    )
    for event in engine.stream(request):
        mapped = engine_event_to_sse(event)
        if mapped is None:
            continue
        event_name, data = mapped
        yield sse_encode(event_name, data)
