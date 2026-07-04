from __future__ import annotations

import json
import time
from typing import Any, Callable

from app.agent_workflow.config import AgentConfig
from app.agent_workflow.context import (
    ContextBuilder,
    extract_source_ref,
    make_artifact_id,
    score_artifact,
    truncate_tool_result,
)
from app.agent_workflow.parsing import parse_executor_action
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.providers.tools import ToolProvider
from app.agent_workflow.state import AgentState, Artifact, ToolCallRecord


def _called_tools_for_step(state: AgentState, step_index: int) -> set[str]:
    return {
        str(artifact.get("tool") or "")
        for artifact in (state.get("artifacts") or [])
        if int(artifact.get("step_index", -1)) == step_index and artifact.get("tool")
    }


def _schema_for_tool(tool_name: str, candidate_tools: list[dict[str, Any]]) -> dict[str, Any]:
    for tool in candidate_tools:
        if tool.get("name") == tool_name:
            schema = tool.get("input_schema") or tool.get("inputSchema") or {}
            return schema if isinstance(schema, dict) else {}
    return {}


def _matches_json_type(value: Any, expected: Any) -> bool:
    if isinstance(expected, list):
        return any(_matches_json_type(value, item) for item in expected)
    if not expected:
        return True
    if expected == "null":
        return value is None
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return True


def _validate_tool_arguments(tool_name: str, arguments: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    if not schema:
        return []

    errors: list[str] = []
    schema_type = schema.get("type")
    if schema_type and not _matches_json_type(arguments, schema_type):
        return [f"{tool_name} arguments must match JSON schema type {schema_type!r}"]

    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    for field in required:
        if field not in arguments or arguments.get(field) is None:
            errors.append(f"missing required argument: {field}")

    if schema.get("additionalProperties") is False and properties:
        for field in sorted(set(arguments) - set(properties)):
            errors.append(f"unexpected argument: {field}")

    for field, value in arguments.items():
        field_schema = properties.get(field)
        if not isinstance(field_schema, dict):
            continue
        expected = field_schema.get("type")
        if expected and not _matches_json_type(value, expected):
            errors.append(f"argument {field} must match JSON schema type {expected!r}")
    return errors


def _record_invalid_tool_arguments(
    *,
    state: AgentState,
    updates: dict[str, Any],
    iteration: dict[str, Any],
    tool_name: str,
    arguments: dict[str, Any],
    errors: list[str],
) -> dict[str, Any]:
    record: ToolCallRecord = {
        "name": tool_name,
        "args_preview": json.dumps(arguments)[:300],
        "status": "invalid_args",
        "latency_ms": 0,
        "error": "; ".join(errors),
    }
    tool_calls = list(state.get("tool_calls") or [])
    tool_calls.append(record)
    iteration["tool_calls"] = int(iteration.get("tool_calls") or 0) + 1
    updates["tool_calls"] = tool_calls
    updates["iteration"] = iteration
    updates["events"].append(
        {
            "step": "executor.tool_args_invalid",
            "tool": tool_name,
            "error": record["error"],
        }
    )
    return updates


def _synthesize_draft_answer(state: AgentState, *, config: AgentConfig, llm: LlmProvider) -> str:
    builder = ContextBuilder(config)
    messages = builder.build(state, "executor")
    messages[-1]["content"] += (
        "\n\nAll plan steps are complete. Write the final user-facing answer using the artifacts above.\n"
        'Return ONLY JSON: {"action":"draft_answer","answer":"..."}'
    )
    raw = llm.complete(messages, max_tokens=2000)
    action = parse_executor_action(raw)
    answer = str(action.get("answer") or raw).strip()
    return answer or _fallback_answer(state)


def _was_denied(state: AgentState, tool_name: str) -> bool:
    return any(
        record.get("name") == tool_name and record.get("status") == "denied"
        for record in (state.get("tool_calls") or [])
    )


def _record_denial(state: AgentState, updates: dict[str, Any], tool_name: str, arguments: dict[str, Any]) -> None:
    record: ToolCallRecord = {
        "name": tool_name,
        "args_preview": json.dumps(arguments)[:300],
        "status": "denied",
        "latency_ms": 0,
        "error": None,
    }
    tool_calls = list(updates.get("tool_calls") or state.get("tool_calls") or [])
    tool_calls.append(record)
    updates["tool_calls"] = tool_calls


def _execute_tool_call_action(
    *,
    state: AgentState,
    config: AgentConfig,
    tools: ToolProvider,
    action: dict[str, Any],
    updates: dict[str, Any],
    iteration: dict[str, Any],
    step_index: int,
    step_query: str,
    on_tool_call: Callable[[str, dict[str, Any], Any], None] | None,
    on_artifact: Callable[[Artifact], None] | None,
    on_destructive_action: Callable[[str, dict[str, Any]], bool] | None,
) -> dict[str, Any]:
    tool_name = str(action.get("name") or "")
    arguments = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
    if not tool_name:
        updates["error"] = "call_tool missing name"
        return updates

    if tool_name in config.policy.destructive_tools and config.policy.require_destructive_confirmation:
        # A destructive call denied earlier in this run must not be re-asked forever.
        if _was_denied(state, tool_name):
            updates["events"].append(
                {"step": "executor.destructive_skipped", "tool": tool_name, "reason": "previously_denied"}
            )
            return updates

        if on_destructive_action is not None:
            # Host supplied a synchronous approver (e.g. interactive CLI).
            if not on_destructive_action(tool_name, arguments):
                _record_denial(state, updates, tool_name, arguments)
                updates["events"].append({"step": "executor.destructive_denied", "tool": tool_name})
                return updates
        else:
            # Fail closed: no approver is wired, so never execute. Park the call
            # in state and pause the graph at the approval node (interrupt), so
            # the host can approve out-of-band and resume from the checkpoint.
            updates["pending_destructive"] = {
                "tool": tool_name,
                "arguments": arguments,
                "step_index": step_index,
                "step_query": step_query,
                "requested_at": time.time(),
            }
            updates["phase"] = "awaiting_approval"
            updates["events"].append(
                {"step": "executor.approval_required", "tool": tool_name, "arguments": arguments}
            )
            return updates

    return _run_tool_and_record(
        state=state,
        config=config,
        tools=tools,
        tool_name=tool_name,
        arguments=arguments,
        updates=updates,
        iteration=iteration,
        step_index=step_index,
        step_query=step_query,
        on_tool_call=on_tool_call,
        on_artifact=on_artifact,
    )


def _run_tool_and_record(
    *,
    state: AgentState,
    config: AgentConfig,
    tools: ToolProvider,
    tool_name: str,
    arguments: dict[str, Any],
    updates: dict[str, Any],
    iteration: dict[str, Any],
    step_index: int,
    step_query: str,
    on_tool_call: Callable[[str, dict[str, Any], Any], None] | None,
    on_artifact: Callable[[Artifact], None] | None,
) -> dict[str, Any]:
    """Execute a tool call and fold the result into state updates.

    No destructive gating here — callers are either non-destructive paths or the
    approval node executing an explicitly approved call.
    """
    started = time.perf_counter()
    status = "ok"
    error: str | None = None
    result: Any = None
    try:
        result = tools.call_tool(tool_name, arguments)
        if on_tool_call:
            on_tool_call(tool_name, arguments, result)
    except Exception as exc:  # noqa: BLE001
        status = "error"
        error = str(exc)
        result = {"ok": False, "error": error}

    latency_ms = int((time.perf_counter() - started) * 1000)
    record: ToolCallRecord = {
        "name": tool_name,
        "args_preview": json.dumps(arguments)[:300],
        "status": status,
        "latency_ms": latency_ms,
        "error": error,
    }
    tool_calls = list(state.get("tool_calls") or [])
    tool_calls.append(record)
    iteration["tool_calls"] = int(iteration.get("tool_calls") or 0) + 1
    updates["tool_calls"] = tool_calls
    updates["iteration"] = iteration

    summary, raw_ref, truncated = truncate_tool_result(
        result,
        step_query=step_query,
        policy=config.policy.truncation,
    )
    scores = score_artifact(
        summary=summary,
        step_query=step_query,
        tool_result=result if isinstance(result, dict) else {"result": result},
        existing_artifacts=state.get("artifacts") or [],
        policy=config.policy.truncation,
        created_at=time.time(),
    )
    artifact: Artifact = {
        "id": make_artifact_id(tool_name, summary),
        "tool": tool_name,
        "summary": summary,
        "raw_ref": raw_ref,
        "source_ref": extract_source_ref(result if isinstance(result, dict) else {}),
        "scores": scores,
        "composite_score": scores["composite"],
        "created_at": time.time(),
        "step_index": step_index,
        "truncated": truncated,
    }
    artifacts = list(state.get("artifacts") or [])
    artifacts.append(artifact)
    updates["artifacts"] = artifacts
    if on_artifact:
        on_artifact(artifact)
    updates["events"].append(
        {
            "step": "executor.call_tool",
            "tool": tool_name,
            "status": status,
            "arguments": arguments,
            "error": error,
        }
    )
    return updates


def executor_node(
    state: AgentState,
    *,
    config: AgentConfig,
    llm: LlmProvider,
    tools: ToolProvider,
    on_tool_search: Callable[[str, list[dict[str, Any]]], None] | None = None,
    on_tool_call: Callable[[str, dict[str, Any], Any], None] | None = None,
    on_artifact: Callable[[Artifact], None] | None = None,
    on_destructive_action: Callable[[str, dict[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    iteration = dict(state.get("iteration") or {})
    iteration["executor_turns"] = int(iteration.get("executor_turns") or 0) + 1
    if iteration["executor_turns"] > config.policy.max_executor_iterations:
        draft = state.get("draft_answer") or _synthesize_draft_answer(state, config=config, llm=llm)
        return {
            "phase": "reviewing",
            "draft_answer": draft,
            "iteration": iteration,
            "events": [{"step": "executor.iteration_limit", "synthesized": True}],
        }

    plan = state.get("plan") or {}
    steps = plan.get("steps") or []
    step_index = int(state.get("current_step_index") or 0)
    if step_index >= len(steps) and not state.get("draft_answer"):
        draft = _synthesize_draft_answer(state, config=config, llm=llm)
        return {
            "phase": "reviewing",
            "draft_answer": draft,
            "iteration": iteration,
            "events": [{"step": "executor.draft_answer", "synthesized": True}],
        }

    current_step = steps[step_index] if step_index < len(steps) else {}
    step_query = " ".join(
        part for part in [current_step.get("title", ""), current_step.get("action", ""), state.get("user_query", "")] if part
    )

    builder = ContextBuilder(config)
    messages = builder.build(state, "executor")
    messages[-1]["content"] += (
        "\n\nReturn ONLY JSON with one action:\n"
        '{"action":"search_tools","query":"..."}\n'
        '{"action":"call_tool","name":"tool_name","arguments":{...}}\n'
        '{"action":"finish_step"}\n'
        '{"action":"draft_answer","answer":"..."}'
    )

    raw = llm.complete(messages, max_tokens=1200)
    action = parse_executor_action(raw)
    action_type = str(action.get("action") or "").lower()

    candidate_tools = list(state.get("candidate_tools") or [])
    called_this_step = _called_tools_for_step(state, step_index)
    updates: dict[str, Any] = {"iteration": iteration, "phase": "executing"}
    updates["events"] = [
        {
            "step": "executor.action",
            "action": action_type,
            "step_index": step_index,
            "step_title": current_step.get("title", ""),
            "executor_turn": iteration["executor_turns"],
        }
    ]

    if action_type == "search_tools" and candidate_tools:
        updates["events"].append(
            {
                "step": "executor.tool_candidates_available",
                "message": "Candidate tools are already available; select call_tool with schema-valid arguments.",
                "tool_count": len(candidate_tools),
            }
        )
        return updates

    if action_type == "call_tool":
        tool_name = str(action.get("name") or "")
        step_call_count = len(called_this_step)
        max_per_step = config.policy.max_tool_calls_per_step
        if tool_name in called_this_step:
            action_type = "finish_step"
            updates["events"].append(
                {
                    "step": "executor.duplicate_tool_skipped",
                    "tool": tool_name,
                    "message": "Tool was already called for this step; finishing instead of overriding the model choice.",
                }
            )
        elif step_call_count >= max_per_step:
            action_type = "finish_step"
            updates["events"].append(
                {
                    "step": "executor.tool_limit_reached",
                    "message": "Maximum tool calls for this step reached; finishing step.",
                }
            )

    if action_type == "search_tools":
        query = str(action.get("query") or step_query)
        try:
            candidates = tools.search_tools(query)
        except Exception as exc:  # noqa: BLE001
            return {
                "error": str(exc),
                "phase": "reviewing",
                "draft_answer": f"Tool search failed: {exc}",
                "iteration": iteration,
                "events": updates["events"],
            }

        candidate_dicts = [
            {
                "name": c.name,
                "title": c.title,
                "description": c.description,
                "score": c.score,
                "input_schema": c.input_schema,
            }
            for c in candidates
        ]
        if not candidate_dicts:
            return {
                "error": f"No tools matched: {query}",
                "phase": "reviewing",
                "draft_answer": (
                    f"No tools matched: {query}. "
                    "Ingest the MCP tool catalog into Qdrant (see mcp-service MCP_TOOL_INDEX_COLLECTION)."
                ),
                "iteration": iteration,
                "events": updates["events"],
            }

        if on_tool_search:
            on_tool_search(query, candidate_dicts)
        updates["candidate_tools"] = candidate_dicts
        updates["events"].append(
            {
                "step": "executor.search_tools",
                "query": query,
                "tool_count": len(candidate_dicts),
                "tools": [c["name"] for c in candidate_dicts[:7]],
            }
        )
        return updates

    if action_type == "call_tool":
        tool_name = str(action.get("name") or "")
        arguments = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
        candidate_names = {str(tool.get("name") or "") for tool in candidate_tools}
        if candidate_tools and tool_name not in candidate_names:
            errors = [f"tool was not discovered for this step: {tool_name}"]
        else:
            schema = _schema_for_tool(tool_name, candidate_tools)
            errors = _validate_tool_arguments(tool_name, arguments, schema)
        if errors:
            return _record_invalid_tool_arguments(
                state=state,
                updates=updates,
                iteration=iteration,
                tool_name=tool_name,
                arguments=arguments,
                errors=errors,
            )
        return _execute_tool_call_action(
            state=state,
            config=config,
            tools=tools,
            action={"action": "call_tool", "name": tool_name, "arguments": arguments},
            updates=updates,
            iteration=iteration,
            step_index=step_index,
            step_query=step_query,
            on_tool_call=on_tool_call,
            on_artifact=on_artifact,
            on_destructive_action=on_destructive_action,
        )

    if action_type == "finish_step":
        next_index = step_index + 1
        updates["current_step_index"] = next_index
        updates["candidate_tools"] = []
        updates["events"].append({"step": "executor.finish_step", "step_index": step_index})
        if next_index >= len(steps):
            updates["phase"] = "executing"
        return updates

    answer = str(action.get("answer") or raw).strip()
    updates["draft_answer"] = answer
    updates["phase"] = "reviewing"
    updates["events"].append({"step": "executor.draft_answer"})
    return updates


def _fallback_answer(state: AgentState) -> str:
    artifacts = state.get("artifacts") or []
    if not artifacts:
        return "I completed the available steps but could not produce a detailed answer."
    lines = ["Here is what I found:"]
    for artifact in artifacts[:5]:
        lines.append(f"- {artifact.get('tool')}: {str(artifact.get('summary', ''))[:400]}")
    return "\n".join(lines)
