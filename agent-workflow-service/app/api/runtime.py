from __future__ import annotations

from pathlib import Path
from typing import Iterator

from app.agent_workflow.engine import AgentEngine
from app.agent_workflow.streaming import RunRequest
from app.api.runtime_bundle_adapter import build_engine_from_runtime_bundle
from app.api.schema import AgentWorkflowRunRequest, AgentWorkflowRuntimeBundleRequest
from app.api.sse_adapter import engine_event_to_sse, sse_encode


_DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[1] / "agent_workflow" / "agents" / "default.yaml"
)


def resolve_engine(payload: AgentWorkflowRunRequest) -> AgentEngine:
    if payload.config is not None:
        if payload.runtime_overrides:
            return AgentEngine.from_runtime_config(payload.config, payload.runtime_overrides)
        return AgentEngine.from_dict(payload.config)

    config_path = Path(payload.config_path).resolve() if payload.config_path else _DEFAULT_CONFIG_PATH
    if payload.runtime_overrides:
        return AgentEngine.from_runtime_config(config_path, payload.runtime_overrides)
    return AgentEngine.from_config(config_path)


def resolve_engine_from_runtime_bundle(payload: AgentWorkflowRuntimeBundleRequest) -> AgentEngine:
    return build_engine_from_runtime_bundle(payload.runtime_bundle)


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
