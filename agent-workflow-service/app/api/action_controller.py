from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.agent_workflow.config import AgentConfig, load_agent_config, merge_agent_config, parse_agent_config
from app.agent_workflow.context import extract_source_ref, make_artifact_id, score_artifact, truncate_tool_result
from app.agent_workflow.exploration_profile import (
    apply_exploration_profile_to_overrides,
    resolve_exploration_profile,
)
from app.agent_workflow.context.builder import ContextBuilder
from app.agent_workflow.follow_up import build_search_query, resolve_follow_up_policy
from app.agent_workflow.graph import (
    _should_compact,
    route_after_executor,
    route_after_planner,
    route_after_reviewer,
    route_after_start,
    route_after_synthesizer,
)
from app.agent_workflow.nodes import (
    executor_node,
    fact_extractor_node,
    finalizer_node,
    planner_node,
    reviewer_node,
    revision_node,
    summarizer_node,
    synthesizer_node,
)
from app.agent_workflow.parsing import parse_executor_action, parse_plan_markdown, parse_review_markdown
from app.agent_workflow.providers.tools import ToolCandidate
from app.agent_workflow.streaming import RunRequest, map_graph_update
from app.agent_workflow.telemetry import trace_event_messages
from app.api.api_response import ApiResponse
from app.api.checkpointer import get_runtime_checkpointer
from app.api.dependencies import require_api_key
from app.api.runtime import _resolve_config_path, _validate_outbound_hosts
from app.api.schema import AgentWorkflowActionRequest
from app.agent_workflow.engine import AgentEngine


router = APIRouter(
    prefix="/api/agent-workflow",
    tags=["agent-workflow-actions"],
    dependencies=[Depends(require_api_key)],
)


_ACTIONS = {
    "actions.list",
    "config.load",
    "config.signature",
    "request.validate",
    "engine.initial_state",
    "engine.can_fast_path",
    "follow_up.build_search_query",
    "follow_up.resolve_policy",
    "profile.resolve",
    "profile.apply",
    "parse.plan",
    "parse.executor_action",
    "parse.review",
    "context.build",
    "truncation.truncate_tool_result",
    "truncation.extract_source_ref",
    "truncation.make_artifact_id",
    "artifact.score",
    "graph.route_after_start",
    "graph.route_after_planner",
    "graph.route_after_executor",
    "graph.route_after_synthesizer",
    "graph.route_after_reviewer",
    "graph.should_compact",
    "streaming.map_graph_update",
    "tool.search",
    "tool.call",
    "node.planner",
    "node.executor",
    "node.fact_extractor",
    "node.summarizer",
    "node.synthesizer",
    "node.reviewer",
    "node.revision",
    "node.finalizer",
}


@dataclass
class _ActionLlm:
    responses: list[str]
    native_response: dict[str, Any] | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "_ActionLlm":
        responses = payload.get("responses")
        if isinstance(responses, list):
            values = [str(item) for item in responses]
        else:
            values = [str(payload.get("response") or "")]
        return cls(responses=values, native_response=payload.get("native_response") if isinstance(payload.get("native_response"), dict) else None)

    def _next(self) -> str:
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0] if self.responses else ""

    def complete(self, messages: Sequence[dict[str, Any]], *, max_tokens: int = 1024) -> str:
        return self._next()

    def stream(self, messages: Sequence[dict[str, Any]], *, max_tokens: int = 1024) -> Iterator[str]:
        yield self._next()

    def complete_with_tools(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        tools: list[dict[str, Any]],
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        if self.native_response is not None:
            return dict(self.native_response)
        return {"content": self._next(), "tool_calls": []}


@dataclass
class _ActionTools:
    candidates: list[ToolCandidate]
    results: dict[str, Any]
    default_result: Any = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "_ActionTools":
        raw_candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
        candidates = []
        for item in raw_candidates:
            if not isinstance(item, dict):
                continue
            candidates.append(
                ToolCandidate(
                    name=str(item.get("name") or ""),
                    title=str(item.get("title") or item.get("name") or ""),
                    description=str(item.get("description") or ""),
                    score=float(item.get("score") or 0.0),
                    input_schema=item.get("input_schema") if isinstance(item.get("input_schema"), dict) else item.get("inputSchema") if isinstance(item.get("inputSchema"), dict) else {},
                )
            )
        results = payload.get("results") if isinstance(payload.get("results"), dict) else {}
        default_result = payload.get("default_result", {"ok": True})
        return cls(candidates=candidates, results=results, default_result=default_result)

    def search_tools(self, query: str, *, limit: int = 25, allowlist: list[str] | None = None) -> list[ToolCandidate]:
        candidates = self.candidates
        if allowlist:
            allowed = set(allowlist)
            candidates = [candidate for candidate in candidates if candidate.name in allowed]
        return candidates[:limit]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        result = self.results.get(name, self.default_result)
        if isinstance(result, dict) and result.get("raise"):
            raise RuntimeError(str(result.get("error") or f"Tool failed: {name}"))
        return result


def _history(payload: AgentWorkflowActionRequest) -> list[dict[str, Any]]:
    return [message.model_dump(mode="json") for message in payload.history]


def _load_config(payload: AgentWorkflowActionRequest) -> AgentConfig:
    if payload.config is not None:
        _validate_outbound_hosts(payload.config)
        config = parse_agent_config(payload.config)
    else:
        config = load_agent_config(_resolve_config_path(payload.config_name, payload.config_path))
    if payload.runtime_overrides:
        _validate_outbound_hosts(payload.runtime_overrides)
        config = merge_agent_config(config, payload.runtime_overrides)
    return config


def _engine(payload: AgentWorkflowActionRequest) -> AgentEngine:
    request_payload = {
        "query": payload.query or "action test",
        "session_id": payload.session_id,
        "history": _history(payload),
        "runtime_context": dict(payload.runtime_context or {}),
        "config_name": payload.config_name,
        "config_path": payload.config_path,
        "config": payload.config,
        "runtime_overrides": payload.runtime_overrides,
    }
    llm = None if payload.use_real_providers else _ActionLlm.from_payload(payload.llm)
    tools = None if payload.use_real_providers else _ActionTools.from_payload(payload.tools)
    if payload.config is not None:
        _validate_outbound_hosts(payload.config)
        if payload.runtime_overrides:
            _validate_outbound_hosts(payload.runtime_overrides)
            return AgentEngine.from_runtime_config(payload.config, payload.runtime_overrides, checkpointer=get_runtime_checkpointer(), llm=llm, tools=tools)
        return AgentEngine.from_dict(payload.config, checkpointer=get_runtime_checkpointer(), llm=llm, tools=tools)
    config_path = _resolve_config_path(payload.config_name, payload.config_path)
    if payload.runtime_overrides:
        _validate_outbound_hosts(payload.runtime_overrides)
        return AgentEngine.from_runtime_config(config_path, payload.runtime_overrides, checkpointer=get_runtime_checkpointer(), llm=llm, tools=tools)
    return AgentEngine.from_config(config_path, checkpointer=get_runtime_checkpointer(), llm=llm, tools=tools)


def _run_request(payload: AgentWorkflowActionRequest) -> RunRequest:
    return RunRequest(
        query=payload.query or str(payload.input.get("query") or "action test"),
        session_id=payload.session_id,
        history=_history(payload),
        runtime_context=dict(payload.runtime_context or {}),
    )


def _state(payload: AgentWorkflowActionRequest, engine: AgentEngine) -> dict[str, Any]:
    if payload.state:
        return dict(payload.state)
    request = engine._validate_request(_run_request(payload))
    return dict(engine._initial_state(request))


def _candidate_dicts(candidates: list[ToolCandidate]) -> list[dict[str, Any]]:
    return [
        {
            "name": candidate.name,
            "title": candidate.title,
            "description": candidate.description,
            "score": candidate.score,
            "input_schema": candidate.input_schema,
        }
        for candidate in candidates
    ]


def _dispatch(payload: AgentWorkflowActionRequest) -> dict[str, Any]:
    action = payload.action.strip()
    if action == "actions.list":
        return {"actions": sorted(_ACTIONS)}
    if action not in _ACTIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported action: {action}")

    engine = _engine(payload)
    config = engine.config
    state = _state(payload, engine)
    data = dict(payload.input or {})

    if action == "config.load":
        return {"config": config.safe_dict()}
    if action == "config.signature":
        return {"signature": config.signature(), "config": config.safe_dict()}
    if action == "request.validate":
        return {"request": engine._validate_request(_run_request(payload)).__dict__}
    if action == "engine.initial_state":
        request = engine._validate_request(_run_request(payload))
        return {"state": dict(engine._initial_state(request, persisted_artifacts=data.get("persisted_artifacts") if isinstance(data.get("persisted_artifacts"), list) else None))}
    if action == "engine.can_fast_path":
        fast_path, reason = engine._can_fast_path(engine._validate_request(_run_request(payload)))
        return {"fast_path": fast_path, "reason": reason}

    if action == "follow_up.build_search_query":
        query = str(data.get("query") or payload.query or "")
        history = data.get("history") if isinstance(data.get("history"), list) else _history(payload)
        return {"search_query": build_search_query(query, history)}
    if action == "follow_up.resolve_policy":
        policy = resolve_follow_up_policy(
            query=str(data.get("query") or payload.query or ""),
            history=data.get("history") if isinstance(data.get("history"), list) else _history(payload),
            persisted_artifacts=data.get("persisted_artifacts") if isinstance(data.get("persisted_artifacts"), list) else [],
            persistence_active=bool(data.get("persistence_active", False)),
            require_tool_on_follow_up=bool(data.get("require_tool_on_follow_up", config.policy.require_tool_on_follow_up)),
        )
        return {"policy": policy.__dict__ | {"required_tools": sorted(policy.required_tools)}}

    if action == "profile.resolve":
        mode = resolve_exploration_profile(
            dict(payload.runtime_context or {}),
            env_default=str(data["env_default"]) if data.get("env_default") is not None else None,
        )
        return {"exploration_profile": mode}
    if action == "profile.apply":
        overrides = dict(data.get("overrides") if isinstance(data.get("overrides"), dict) else (payload.runtime_overrides or {}))
        mode = apply_exploration_profile_to_overrides(
            overrides,
            dict(payload.runtime_context or {}),
            env_default=str(data["env_default"]) if data.get("env_default") is not None else None,
        )
        return {"exploration_profile": mode, "overrides": overrides}

    if action == "parse.plan":
        return {"plan": dict(parse_plan_markdown(str(data.get("text") or "")))}
    if action == "parse.executor_action":
        return {"executor_action": parse_executor_action(str(data.get("text") or ""))}
    if action == "parse.review":
        return {"review": dict(parse_review_markdown(str(data.get("text") or "")))}

    if action == "context.build":
        role = str(data.get("role") or "executor")
        if role not in {"planner", "executor", "reviewer"}:
            raise HTTPException(status_code=400, detail="context.build role must be planner, executor, or reviewer")
        return {"messages": ContextBuilder(config).build(state, role)}

    if action == "truncation.truncate_tool_result":
        summary, raw_ref, truncated = truncate_tool_result(
            data.get("tool_result"),
            step_query=str(data.get("step_query") or state.get("user_query") or ""),
            policy=config.policy.truncation,
        )
        return {"summary": summary, "raw_ref": raw_ref, "truncated": truncated}
    if action == "truncation.extract_source_ref":
        return {"source_ref": extract_source_ref(data.get("tool_result"))}
    if action == "truncation.make_artifact_id":
        return {"artifact_id": make_artifact_id(str(data.get("tool") or "tool"), str(data.get("summary") or ""))}
    if action == "artifact.score":
        scores = score_artifact(
            summary=str(data.get("summary") or ""),
            step_query=str(data.get("step_query") or state.get("user_query") or ""),
            tool_result=data.get("tool_result"),
            existing_artifacts=data.get("existing_artifacts") if isinstance(data.get("existing_artifacts"), list) else list(state.get("artifacts") or []),
            policy=config.policy.truncation,
            semantic_score=data.get("semantic_score"),
            created_at=data.get("created_at"),
        )
        return {"scores": scores}

    if action == "graph.route_after_start":
        return {"route": route_after_start(state)}
    if action == "graph.route_after_planner":
        return {"route": route_after_planner(state)}
    if action == "graph.route_after_executor":
        return {"route": route_after_executor(state, config=config)}
    if action == "graph.route_after_synthesizer":
        return {"route": route_after_synthesizer(state)}
    if action == "graph.route_after_reviewer":
        return {"route": route_after_reviewer(state)}
    if action == "graph.should_compact":
        return {"should_compact": _should_compact(state, config)}
    if action == "streaming.map_graph_update":
        update = data.get("update") if isinstance(data.get("update"), dict) else {}
        node_name = data.get("node_name")
        events = map_graph_update(update, state, node_name=str(node_name) if node_name else None)
        return {"events": events, "debug_trace": trace_event_messages(events)}

    if action == "tool.search":
        candidates = engine.tools.search_tools(
            str(data.get("query") or payload.query or ""),
            limit=int(data.get("limit") or 25),
            allowlist=data.get("allowlist") if isinstance(data.get("allowlist"), list) else config.policy.tools.allowlist,
        )
        return {"tools": _candidate_dicts(candidates)}
    if action == "tool.call":
        name = str(data.get("name") or "")
        if not name:
            raise HTTPException(status_code=400, detail="tool.call requires input.name")
        arguments = data.get("arguments") if isinstance(data.get("arguments"), dict) else {}
        return {"result": engine.tools.call_tool(name, arguments)}

    if action == "node.planner":
        return {"update": planner_node(state, config=config, llm=engine.llm)}
    if action == "node.executor":
        return {"update": executor_node(state, config=config, llm=engine.llm, tools=engine.tools)}
    if action == "node.fact_extractor":
        return {"update": fact_extractor_node(state, config=config)}
    if action == "node.summarizer":
        return {"update": summarizer_node(state, config=config, llm=engine.llm)}
    if action == "node.synthesizer":
        return {"update": synthesizer_node(state, config=config, llm=engine.llm)}
    if action == "node.reviewer":
        return {"update": reviewer_node(state, config=config, llm=engine.llm)}
    if action == "node.revision":
        return {"update": revision_node(state, config=config, llm=engine.llm)}
    if action == "node.finalizer":
        return {"update": finalizer_node(state, config=config, llm=engine.llm)}

    raise HTTPException(status_code=400, detail=f"Unhandled action: {action}")


@router.post("/actions", response_model=ApiResponse[dict])
def run_agent_workflow_action(payload: AgentWorkflowActionRequest):
    """Run one isolated workflow action for Postman/manual node testing."""
    return ApiResponse.ok({"action": payload.action, **_dispatch(payload)})
