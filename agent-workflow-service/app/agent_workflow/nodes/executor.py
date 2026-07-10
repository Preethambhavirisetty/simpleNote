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
from app.agent_workflow.deadlines import DeadlineExceeded, run_with_deadline
from app.agent_workflow.follow_up import follow_up_tool_recall_missing
from app.agent_workflow.parsing import parse_executor_action
from app.agent_workflow.parsing import normalize_tool_name
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.providers.tools import ToolProvider
from app.agent_workflow.state import AgentState, Artifact, ToolCallRecord
from app.agent_workflow.telemetry import llm_call
from app.agent_workflow.util.context_path import resolve_context_path


def _complete_llm(llm: LlmProvider, messages: list[dict[str, str]], *, max_tokens: int, node: str, label: str) -> str:
    """Run an executor LLM call inside the debug trace wrapper."""
    with llm_call(node=node, label=label, messages=messages, max_tokens=max_tokens):
        return llm.complete(messages, max_tokens=max_tokens)


def _complete_with_tools_llm(
    llm: LlmProvider,
    messages: list[dict[str, str]],
    *,
    tools: list[dict[str, Any]],
    max_tokens: int,
) -> dict[str, Any]:
    """Run a native tool-calling LLM turn and trace its token usage."""
    with llm_call(node="executor", label="choose_native_tool", messages=messages, max_tokens=max_tokens):
        return llm.complete_with_tools(messages, tools=tools, max_tokens=max_tokens)


def _current_replan_id(state: AgentState) -> int:
    iteration = state.get("iteration") or {}
    return int(iteration.get("replans") or 0)


def _called_tools_for_step(state: AgentState, step_index: int) -> set[str]:
    """Return tool names already called for the current plan step and replan.

    Reads both artifacts and tool_calls: the summarizer can compact artifacts
    away mid-loop, but tool_calls persist, so duplicate-tool and required-tool
    checks must not forget a call just because its artifact was folded.
    """
    replan_id = _current_replan_id(state)
    called: set[str] = set()
    for artifact in state.get("artifacts") or []:
        if (
            int(artifact.get("step_index", -1)) == step_index
            and int(artifact.get("replan_id") or 0) == replan_id
            and artifact.get("tool")
        ):
            called.add(normalize_tool_name(artifact.get("tool")))
    for record in state.get("tool_calls") or []:
        if (
            int(record.get("step_index", -1)) == step_index
            and int(record.get("replan_id") or 0) == replan_id
            and record.get("name")
        ):
            called.add(normalize_tool_name(record.get("name")))
    return called


def _called_tools_for_run(state: AgentState) -> set[str]:
    """Return successful tool names called anywhere in the current replan."""
    replan_id = _current_replan_id(state)
    called: set[str] = set()
    for record in state.get("tool_calls") or []:
        if (
            int(record.get("replan_id") or 0) == replan_id
            and str(record.get("status") or "") == "ok"
            and record.get("name")
        ):
            called.add(normalize_tool_name(record.get("name")))
    return called


def _step_has_evidence(state: AgentState, step_index: int) -> bool:
    """Return whether the current plan step produced at least one successful tool result."""
    replan_id = _current_replan_id(state)
    for record in state.get("tool_calls") or []:
        if (
            int(record.get("step_index", -1)) == step_index
            and int(record.get("replan_id") or 0) == replan_id
            and str(record.get("status") or "") == "ok"
        ):
            return True
    for artifact in state.get("artifacts") or []:
        if (
            int(artifact.get("step_index", -1)) == step_index
            and int(artifact.get("replan_id") or 0) == replan_id
        ):
            return True
    return False


def _step_call_signatures_and_count(state: AgentState, step_index: int) -> tuple[set[tuple[str, str]], int]:
    """Return (name, args-preview) signatures and the total call count for a step.

    Signatures are what the duplicate guard compares against, so the same tool
    with different arguments is allowed while an identical repeat is skipped. The
    count is the per-step tool-call budget denominator.
    """
    replan_id = _current_replan_id(state)
    signatures: set[tuple[str, str]] = set()
    count = 0
    for record in state.get("tool_calls") or []:
        if int(record.get("step_index", -1)) == step_index and int(record.get("replan_id") or 0) == replan_id and record.get("name"):
            signatures.add((str(record.get("name")), str(record.get("args_preview") or "")))
            count += 1
    return signatures, count


def _update_no_progress(state: AgentState, iteration: dict[str, Any], config: AgentConfig) -> tuple[bool, dict[str, Any]]:
    """Track score-based progress and signal an early stop when exploration stalls.

    Generic and app-agnostic: "progress" is a new artifact scoring at least
    ``min_progress_score``. If ``max_no_progress_turns`` consecutive turns add
    none, the executor should stop exploring and answer with what it already has.
    Search turns do not create tool calls, so pre-call setup is not counted.
    """
    cap = int(config.policy.max_no_progress_turns)
    if cap <= 0:
        return False, iteration
    threshold = float(config.policy.min_progress_score)
    useful = sum(
        1
        for artifact in (state.get("artifacts") or [])
        if float(artifact.get("composite_score") or 0.0) >= threshold
    )
    last_useful = int(iteration.get("useful_artifacts_seen") or 0)
    iteration["useful_artifacts_seen"] = useful
    # Only count stalls once the agent has actually attempted a tool call.
    if not state.get("tool_calls"):
        iteration["no_progress_turns"] = 0
        return False, iteration
    if useful > last_useful:
        iteration["no_progress_turns"] = 0
        return False, iteration
    no_progress = int(iteration.get("no_progress_turns") or 0) + 1
    iteration["no_progress_turns"] = no_progress
    return no_progress >= cap, iteration


def _finish_is_deadlocked(iteration: dict[str, Any], config: AgentConfig) -> bool:
    """Return whether finish_step guards have blocked progress for too long.

    The finish_step guards (follow-up recall, stop_condition, required tools)
    each veto a premature finish by returning without advancing. That is correct
    once, but if the executor keeps arriving at finish_step while producing no new
    evidence, the guards and the model's repeated action deadlock (a repeated
    duplicate call is coerced to finish, then vetoed, then repeated). The generic
    no-progress counter is the arbitration signal: once it reaches the cap the
    step cannot make progress, so the veto must yield and let the step advance
    rather than burn the whole iteration budget.
    """
    cap = int(config.policy.max_no_progress_turns)
    return cap > 0 and int(iteration.get("no_progress_turns") or 0) >= cap


def _cache_key(query: str) -> str:
    """Normalize a query into a short stable cache key."""
    return " ".join(query.lower().split())[:300]


def _prune_tool_calls(records: list[ToolCallRecord], *, config: AgentConfig) -> list[ToolCallRecord]:
    """Prune tool calls to the configured retention limit."""
    limit = max(0, int(config.policy.max_retained_tool_calls))
    return records[-limit:] if limit else []


def _prune_artifacts(artifacts: list[Artifact], *, config: AgentConfig) -> list[Artifact]:
    """Prune artifacts to the configured retention limit."""
    limit = max(0, int(config.policy.max_retained_artifacts))
    if not limit:
        return []
    if len(artifacts) <= limit:
        return artifacts
    ranked = sorted(
        enumerate(artifacts),
        key=lambda item: (float(item[1].get("composite_score") or 0.0), int(item[0])),
        reverse=True,
    )[:limit]
    keep_indexes = {idx for idx, _artifact in ranked}
    return [artifact for idx, artifact in enumerate(artifacts) if idx in keep_indexes]


def _prune_tool_discovery_cache(
    cache: dict[str, list[dict[str, Any]]],
    *,
    config: AgentConfig,
) -> dict[str, list[dict[str, Any]]]:
    """Prune tool discovery cache to the configured retention limit."""
    limit = max(0, int(config.policy.tool_discovery_cache_size))
    if not limit:
        return {}
    items = list(cache.items())[-limit:]
    return dict(items)


def _schema_for_tool(tool_name: str, candidate_tools: list[dict[str, Any]]) -> dict[str, Any]:
    """Find the JSON input schema for a discovered tool."""
    for tool in candidate_tools:
        if tool.get("name") == tool_name:
            schema = tool.get("input_schema") or tool.get("inputSchema") or {}
            return schema if isinstance(schema, dict) else {}
    return {}


def _is_tool_allowed(tool_name: str, *, config: AgentConfig) -> bool:
    """Return whether the configured tool policy allows this tool."""
    allowlist = {item for item in (config.policy.tools.allowlist or []) if item}
    denylist = {item for item in (config.policy.tools.denylist or []) if item}
    if tool_name in denylist:
        return False
    if not allowlist:
        return True
    return tool_name in allowlist


def _filter_candidates_by_policy(candidates: list[dict[str, Any]], *, config: AgentConfig) -> list[dict[str, Any]]:
    """Remove discovered tools blocked by allowlist or denylist policy."""
    filtered = []
    for candidate in candidates:
        tool_name = str(candidate.get("name") or "")
        if tool_name and _is_tool_allowed(tool_name, config=config):
            filtered.append(candidate)
    return filtered


def _required_tools_for_step(config: AgentConfig, step: dict[str, Any]) -> set[str]:
    """Return tool names that must run before this step can finish."""
    required = {normalize_tool_name(tool) for tool in (step.get("required_tools") or []) if normalize_tool_name(tool)}
    hint = normalize_tool_name(step.get("tool_hint"))
    if hint and hint.lower() not in {"auto", "none", "any"}:
        required.add(hint)
    title = str(step.get("title") or "")
    for key, tools in (config.policy.tools.required_tools or {}).items():
        if key == "*" or (title and key.lower() in title.lower()):
            required.update(normalize_tool_name(tool) for tool in (tools or []) if normalize_tool_name(tool))
    denylist = {normalize_tool_name(item) for item in (config.policy.tools.denylist or []) if normalize_tool_name(item)}
    return {tool for tool in required if tool and tool not in denylist}


def _plan_steps_incomplete(state: AgentState, config: AgentConfig) -> bool:
    """Return whether the executor still has unfinished plan work."""
    steps = (state.get("plan") or {}).get("steps") or []
    if not steps:
        return False
    step_index = int(state.get("current_step_index") or 0)
    if step_index >= len(steps):
        return False
    current_step = steps[step_index]
    required = _required_tools_for_step(config, current_step)
    called = _called_tools_for_step(state, step_index) | _called_tools_for_run(state)
    if required - called:
        return True
    stop_condition = str(current_step.get("stop_condition") or "").strip()
    if stop_condition and not _step_has_evidence(state, step_index):
        return True
    return step_index < len(steps) - 1


def _apply_argument_injection(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    schema: dict[str, Any],
    runtime_context: dict[str, Any],
    config: AgentConfig,
) -> dict[str, Any]:
    """Inject trusted runtime-context values into tool arguments."""
    mapping = dict((config.policy.tools.argument_injection or {}).get(tool_name) or {})
    if not mapping or not schema:
        return arguments
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    if not properties:
        return arguments
    injected = dict(arguments)
    for arg_name, path in mapping.items():
        if arg_name not in properties:
            continue
        value = resolve_context_path(runtime_context, str(path))
        if value is None:
            continue
        injected[arg_name] = value
    return injected


def _matches_json_type(value: Any, expected: Any) -> bool:
    """Helper for matches json type."""
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
    """Validate tool arguments and raise or return errors when invalid."""
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
    config: AgentConfig,
    updates: dict[str, Any],
    iteration: dict[str, Any],
    tool_name: str,
    arguments: dict[str, Any],
    errors: list[str],
) -> dict[str, Any]:
    """Record invalid tool arguments into workflow state or telemetry."""
    record: ToolCallRecord = {
        "name": tool_name,
        "args_preview": json.dumps(arguments)[:300],
        "status": "invalid_args",
        "latency_ms": 0,
        "error": "; ".join(errors),
    }
    tool_calls = list(state.get("tool_calls") or [])
    tool_calls.append(record)
    tool_calls = _prune_tool_calls(tool_calls, config=config)
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


def _search_repeat_counter(iteration: dict[str, Any], *, step_index: int) -> int:
    """Search repeat counter and return matching candidates."""
    prev_step = int(iteration.get("search_repeat_step", -1))
    if prev_step != step_index:
        iteration["search_repeat_step"] = step_index
        iteration["search_repeat_count"] = 0
    count = int(iteration.get("search_repeat_count") or 0) + 1
    iteration["search_repeat_count"] = count
    return count


def _native_tool_specs(candidates: list[dict[str, Any]], *, config: AgentConfig) -> list[dict[str, Any]]:
    """Convert discovered tools into OpenAI native tool-call specs."""
    limits = config.policy.executor
    specs = []
    for candidate in candidates[: limits.max_native_tools]:
        name = str(candidate.get("name") or "").strip()
        if not name:
            continue
        schema = candidate.get("input_schema") or candidate.get("inputSchema") or {}
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": str(candidate.get("description") or "")[: limits.tool_description_max_chars],
                    "parameters": schema if isinstance(schema, dict) and schema else {"type": "object"},
                },
            }
        )
    return specs


def _prefetch_candidate_tools(
    state: AgentState,
    *,
    config: AgentConfig,
    tools: ToolProvider,
    step_query: str,
    on_tool_search: Callable[[str, list[dict[str, Any]]], None] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    """Discover tools for the step without spending an LLM roundtrip.

    In native tool-calling mode the model never has to emit a search_tools
    action: candidates are fetched deterministically from the step text.
    Returns (policy-filtered candidates, events, discovery-cache update).
    """
    key = _cache_key(step_query)
    discovery_cache = dict(state.get("tool_discovery_cache") or {})
    candidate_dicts = list(discovery_cache.get(key) or [])
    cache_hit = bool(candidate_dicts)
    cache_update: dict[str, Any] | None = None
    if not candidate_dicts:
        try:
            candidates = tools.search_tools(step_query, allowlist=config.policy.tools.allowlist)
        except Exception as exc:  # noqa: BLE001 — model falls back to its own search action
            return [], [{"step": "executor.search_tools_failed", "query": step_query, "error": str(exc)[:300]}], None
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
        if candidate_dicts:
            discovery_cache[key] = candidate_dicts
            cache_update = _prune_tool_discovery_cache(discovery_cache, config=config)
    candidate_dicts = _filter_candidates_by_policy(candidate_dicts, config=config)
    events: list[dict[str, Any]] = []
    if candidate_dicts:
        if on_tool_search:
            on_tool_search(step_query, candidate_dicts)
        events.append(
            {
                "step": "executor.search_tools",
                "query": step_query,
                "cache_hit": cache_hit,
                "tool_count": len(candidate_dicts),
                "tools": [c["name"] for c in candidate_dicts[: config.policy.context.max_tools_in_prompt]],
                "native_prefetch": True,
            }
        )
    return candidate_dicts, events, cache_update


def _was_denied(state: AgentState, tool_name: str) -> bool:
    """Helper for was denied."""
    return any(
        record.get("name") == tool_name and record.get("status") == "denied"
        for record in (state.get("tool_calls") or [])
    )


def _record_denial(
    state: AgentState,
    config: AgentConfig,
    updates: dict[str, Any],
    tool_name: str,
    arguments: dict[str, Any],
) -> None:
    """Record a denied destructive tool call without executing it."""
    record: ToolCallRecord = {
        "name": tool_name,
        "args_preview": json.dumps(arguments)[:300],
        "status": "denied",
        "latency_ms": 0,
        "error": None,
    }
    tool_calls = list(updates.get("tool_calls") or state.get("tool_calls") or [])
    tool_calls.append(record)
    tool_calls = _prune_tool_calls(tool_calls, config=config)
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
    """Helper for execute tool call action."""
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
                _record_denial(state, config, updates, tool_name, arguments)
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
        result = run_with_deadline(
            lambda: tools.call_tool(tool_name, arguments),
            timeout_seconds=config.policy.tool_timeout_seconds,
            label=f"tool call {tool_name}",
        )
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
        "step_index": step_index,
        "replan_id": _current_replan_id(state),
    }
    tool_calls = list(state.get("tool_calls") or [])
    tool_calls.append(record)
    tool_calls = _prune_tool_calls(tool_calls, config=config)
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
        "replan_id": _current_replan_id(state),
        "truncated": truncated,
    }
    artifacts = list(state.get("artifacts") or [])
    artifacts.append(artifact)
    updates["artifacts"] = _prune_artifacts(artifacts, config=config)
    if on_artifact:
        on_artifact(artifact)
    updates["events"].append(
        {
            "step": "executor.call_tool",
            "tool": tool_name,
            "status": status,
            "arguments": arguments,
            "error": error,
            "latency_ms": latency_ms,
            "artifact_id": artifact.get("id"),
            "artifact_score": round(float(artifact.get("composite_score") or 0.0), 3),
            "artifact_truncated": truncated,
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
    # The executor owns the active step: it discovers tools, validates tool
    # arguments, records artifacts, and decides when a draft is ready.
    """Execute the current plan step by choosing actions, calling tools, and drafting answers."""
    iteration = dict(state.get("iteration") or {})
    iteration["executor_turns"] = int(iteration.get("executor_turns") or 0) + 1
    if iteration["executor_turns"] > config.policy.max_executor_iterations:
        return {
            "phase": "fact_extracting",
            "iteration": iteration,
            "events": [{"step": "executor.iteration_limit", "handoff": "fact_extractor"}],
        }

    # Generic early stop: once tool work stops producing useful new evidence,
    # stop exploring and answer with what we have rather than burning the budget.
    stalled, iteration = _update_no_progress(state, iteration, config)
    if stalled and not _plan_steps_incomplete(state, config):
        return {
            "phase": "fact_extracting",
            "iteration": iteration,
            "events": [
                {
                    "step": "executor.no_progress_stop",
                    "handoff": "fact_extractor",
                    "no_progress_turns": int(iteration.get("no_progress_turns") or 0),
                    "useful_artifacts": int(iteration.get("useful_artifacts_seen") or 0),
                }
            ],
        }

    plan = state.get("plan") or {}
    steps = plan.get("steps") or []
    step_index = int(state.get("current_step_index") or 0)
    if step_index >= len(steps):
        return {
            "phase": "fact_extracting",
            "iteration": iteration,
            "events": [{"step": "executor.completed_steps", "handoff": "fact_extractor"}],
        }

    current_step = steps[step_index] if step_index < len(steps) else {}
    # Prefer the planner-rewritten standalone query (pronouns resolved) so
    # semantic tool search on follow-ups matches on real nouns, not "them"/"it".
    retrieval_query = str(state.get("search_query") or state.get("user_query", ""))
    step_query = " ".join(
        part for part in [current_step.get("title", ""), current_step.get("action", ""), retrieval_query] if part
    )

    native_mode = bool(config.llm.native_tool_calling) and callable(getattr(llm, "complete_with_tools", None))
    prefetch_events: list[dict[str, Any]] = []
    prefetch_candidates: list[dict[str, Any]] = []
    prefetch_cache_update: dict[str, Any] | None = None
    if native_mode and not state.get("candidate_tools"):
        prefetch_candidates, prefetch_events, prefetch_cache_update = _prefetch_candidate_tools(
            state, config=config, tools=tools, step_query=step_query, on_tool_search=on_tool_search
        )
        if prefetch_candidates:
            state = {**state, "candidate_tools": prefetch_candidates}
        if prefetch_cache_update is not None:
            state = {**state, "tool_discovery_cache": prefetch_cache_update}

    builder = ContextBuilder(config)
    messages = builder.build(state, "executor")
    native_candidates = (
        _filter_candidates_by_policy(list(state.get("candidate_tools") or []), config=config)
        if native_mode
        else []
    )
    use_native = bool(native_candidates)
    if use_native:
        messages[-1]["content"] += (
            "\n\nCall one of the provided tools directly when tool output is needed."
            "\nWhen no tool call is needed, return ONLY JSON with one action:\n"
            '{"action":"finish_step"}\n'
            '{"action":"draft_answer","answer":"..."}\n'
            '{"action":"search_tools","query":"..."}'
        )
    else:
        messages[-1]["content"] += (
            "\n\nReturn ONLY JSON with one action:\n"
            '{"action":"search_tools","query":"..."}\n'
            '{"action":"call_tool","name":"tool_name","arguments":{...}}\n'
            '{"action":"finish_step"}\n'
            '{"action":"draft_answer","answer":"..."}'
        )

    action: dict[str, Any] | None = None
    raw = ""
    try:
        if use_native:
            try:
                response = run_with_deadline(
                    lambda: _complete_with_tools_llm(
                        llm,
                        messages,
                        tools=_native_tool_specs(native_candidates, config=config),
                        max_tokens=config.policy.executor.native_tool_max_tokens,
                    ),
                    timeout_seconds=config.policy.llm_timeout_seconds,
                    label="executor LLM call",
                )
            except DeadlineExceeded:
                raise
            except Exception as exc:  # noqa: BLE001 — provider may not support the tools contract
                prefetch_events.append({"step": "executor.native_fallback", "error": str(exc)[:300]})
                response = None
            if response is not None:
                native_calls = list(response.get("tool_calls") or [])
                if native_calls:
                    first = native_calls[0]
                    action = {
                        "action": "call_tool",
                        "name": str(first.get("name") or ""),
                        "arguments": first.get("arguments") if isinstance(first.get("arguments"), dict) else {},
                    }
                    raw = json.dumps(action)
                    if len(native_calls) > 1:
                        # One action per turn keeps the destructive gate and
                        # per-step caps simple; the model re-requests the rest.
                        prefetch_events.append(
                            {
                                "step": "executor.native_tool_calls_deferred",
                                "count": len(native_calls) - 1,
                                "tools": [str(c.get("name") or "") for c in native_calls[1:5]],
                            }
                        )
                else:
                    raw = str(response.get("content") or "")
        if action is None and not raw:
            raw = run_with_deadline(
                lambda: _complete_llm(
                    llm,
                    messages,
                    max_tokens=config.policy.executor.choose_action_max_tokens,
                    node="executor",
                    label="choose_action",
                ),
                timeout_seconds=config.policy.llm_timeout_seconds,
                label="executor LLM call",
            )
    except DeadlineExceeded as exc:
        return {
            "phase": "fact_extracting",
            "iteration": iteration,
            "error": str(exc),
            "events": [{"step": "executor.timeout", "error": str(exc), "handoff": "fact_extractor"}],
        }
    if action is None:
        action = parse_executor_action(raw)
    action_type = str(action.get("action") or "").lower()

    candidate_tools = _filter_candidates_by_policy(list(state.get("candidate_tools") or []), config=config)
    called_this_step = _called_tools_for_step(state, step_index)
    updates: dict[str, Any] = {"iteration": iteration, "phase": "executing"}
    if prefetch_candidates:
        updates["candidate_tools"] = prefetch_candidates
    if prefetch_cache_update is not None:
        updates["tool_discovery_cache"] = prefetch_cache_update
    updates["events"] = prefetch_events + [
        {
            "step": "executor.action",
            "action": action_type,
            "step_index": step_index,
            "step_title": current_step.get("title", ""),
            "executor_turn": iteration["executor_turns"],
        }
    ]

    if action_type == "search_tools" and candidate_tools:
        repeat_count = _search_repeat_counter(iteration, step_index=step_index)
        updates["iteration"] = iteration
        if repeat_count == 1:
            updates["events"].append(
                {
                    "step": "executor.tool_candidates_available",
                    "message": "Candidate tools are already available; select call_tool with schema-valid arguments.",
                    "tool_count": len(candidate_tools),
                }
            )
            return updates

        if repeat_count == 2 and not called_this_step:
            picked = candidate_tools[0]
            action_type = "call_tool"
            action = {"action": "call_tool", "name": picked.get("name"), "arguments": {}}
            updates["events"].append(
                {
                    "step": "executor.search_loop_breaker",
                    "message": f"Repeated search_tools with candidates; forcing call_tool({picked.get('name')}).",
                }
            )
        else:
            action_type = "finish_step"
            updates["events"].append(
                {
                    "step": "executor.search_loop_breaker",
                    "message": "Repeated search_tools with existing candidates; finishing step to avoid loop.",
                }
            )
    else:
        iteration["search_repeat_count"] = 0
        iteration["search_repeat_step"] = step_index
        updates["iteration"] = iteration

    if action_type == "call_tool":
        tool_name = str(action.get("name") or "")
        # Compare the post-injection argument preview (the same shape stored on the
        # tool-call record) so the same tool with *different* arguments is allowed —
        # e.g. a second get_panel_data with different panel_tokens — while an exact
        # repeat is skipped. The per-step budget counts total calls, not distinct
        # tool names, so a re-explore step gets a fresh budget of its own.
        proposed_args = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
        injected_args = _apply_argument_injection(
            tool_name=tool_name,
            arguments=proposed_args,
            schema=_schema_for_tool(tool_name, candidate_tools),
            runtime_context=dict(state.get("runtime_context") or {}),
            config=config,
        )
        call_signature = (tool_name, json.dumps(injected_args)[:300])
        called_signatures, step_call_count = _step_call_signatures_and_count(state, step_index)
        max_per_step = config.policy.max_tool_calls_per_step
        if call_signature in called_signatures:
            action_type = "finish_step"
            updates["events"].append(
                {
                    "step": "executor.duplicate_tool_skipped",
                    "tool": tool_name,
                    "message": "Tool was already called with identical arguments for this step; finishing instead of repeating it.",
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
        key = _cache_key(query)
        discovery_cache = dict(state.get("tool_discovery_cache") or {})
        candidate_dicts = list(discovery_cache.get(key) or [])
        cache_hit = bool(candidate_dicts)

        if not candidate_dicts:
            try:
                candidates = tools.search_tools(query, allowlist=config.policy.tools.allowlist)
            except Exception as exc:  # noqa: BLE001
                return {
                    "error": str(exc),
                    "phase": "fact_extracting",
                    "draft_answer": f"Tool search failed: {exc}",
                    "draft_kind": "mechanical",
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
            if candidate_dicts:
                discovery_cache[key] = candidate_dicts
                updates["tool_discovery_cache"] = _prune_tool_discovery_cache(discovery_cache, config=config)
        if not candidate_dicts:
            return {
                "error": f"No tools matched: {query}",
                "phase": "fact_extracting",
                "draft_answer": (
                    f"No tools matched: {query}. "
                    "Ingest the MCP tool catalog into Qdrant (see mcp-service MCP_TOOL_INDEX_COLLECTION)."
                ),
                "iteration": iteration,
                "events": updates["events"],
            }

        candidate_dicts = _filter_candidates_by_policy(candidate_dicts, config=config)
        if not candidate_dicts:
            return {
                "error": "Tool policy blocked all discovered tools for this step.",
                "phase": "fact_extracting",
                "draft_answer": "No allowed tools are available for this step under the configured tool policy.",
                "iteration": iteration,
                "events": updates["events"] + [
                    {
                        "step": "executor.tool_policy_blocked",
                        "query": query,
                        "message": "Tool policy blocked all discovered tools for this step.",
                    }
                ],
            }

        if on_tool_search:
            on_tool_search(query, candidate_dicts)
        updates["candidate_tools"] = candidate_dicts
        updates["events"].append(
            {
                "step": "executor.search_tools",
                "query": query,
                "cache_hit": cache_hit,
                "tool_count": len(candidate_dicts),
                "tools": [c["name"] for c in candidate_dicts[: config.policy.context.max_tools_in_prompt]],
            }
        )
        return updates

    if action_type == "call_tool":
        tool_name = str(action.get("name") or "")
        arguments = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
        if not _is_tool_allowed(tool_name, config=config):
            return _record_invalid_tool_arguments(
                state=state,
                config=config,
                updates=updates,
                iteration=iteration,
                tool_name=tool_name,
                arguments=arguments,
                errors=[f"tool blocked by policy: {tool_name}"],
            )
        candidate_names = {str(tool.get("name") or "") for tool in candidate_tools}
        if candidate_tools and tool_name not in candidate_names:
            errors = [f"tool was not discovered for this step: {tool_name}"]
        else:
            schema = _schema_for_tool(tool_name, candidate_tools)
            arguments = _apply_argument_injection(
                tool_name=tool_name,
                arguments=arguments,
                schema=schema,
                runtime_context=dict(state.get("runtime_context") or {}),
                config=config,
            )
            errors = _validate_tool_arguments(tool_name, arguments, schema)
        if errors:
            return _record_invalid_tool_arguments(
                state=state,
                config=config,
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
        # A single arbitration point: the finish guards may veto a premature
        # finish, but only until the step is deadlocked (no new evidence for
        # max_no_progress_turns). Past that, vetoing again would just spin the
        # same coerced-finish loop, so the step is force-advanced instead.
        deadlocked = _finish_is_deadlocked(iteration, config)
        if not deadlocked:
            missing_follow_up = follow_up_tool_recall_missing(state)
            if missing_follow_up:
                updates["events"].append(
                    {
                        "step": "executor.follow_up_evidence_missing",
                        "step_index": step_index,
                        "missing": missing_follow_up,
                        "message": missing_follow_up[0],
                    }
                )
                return updates
            stop_condition = str(current_step.get("stop_condition") or "").strip()
            if stop_condition and not _step_has_evidence(state, step_index):
                updates["events"].append(
                    {
                        "step": "executor.stop_condition_unmet",
                        "step_index": step_index,
                        "stop_condition": stop_condition,
                        "message": (
                            f"Stop condition not met yet: {stop_condition}. "
                            "Call tools and gather evidence before finish_step."
                        ),
                    }
                )
                return updates
            required_tools = _required_tools_for_step(config, current_step)
            called = _called_tools_for_step(state, step_index) | _called_tools_for_run(state)
            missing_required = sorted(required_tools - called)
            if missing_required:
                updates["events"].append(
                    {
                        "step": "executor.required_tools_missing",
                        "step_index": step_index,
                        "required_tools": missing_required,
                        "message": f"Required tools not yet called: {', '.join(missing_required)}",
                    }
                )
                return updates
        else:
            updates["events"].append(
                {
                    "step": "executor.finish_deadlock_break",
                    "step_index": step_index,
                    "no_progress_turns": int(iteration.get("no_progress_turns") or 0),
                    "message": "Step guards blocked finish with no new evidence; advancing to avoid a loop.",
                }
            )
        next_index = step_index + 1
        # Each step gets a fresh stall budget so a deadlock on one step does not
        # immediately trip the no-progress stop on the next.
        iteration["no_progress_turns"] = 0
        updates["iteration"] = iteration
        updates["current_step_index"] = next_index
        updates["candidate_tools"] = []
        updates["events"].append({"step": "executor.finish_step", "step_index": step_index})
        if next_index >= len(steps):
            updates["phase"] = "fact_extracting"
            updates["events"].append({"step": "executor.completed_steps", "handoff": "fact_extractor"})
        return updates

    answer = str(action.get("answer") or raw).strip()
    missing_follow_up = follow_up_tool_recall_missing(state)
    if missing_follow_up:
        updates["events"].append(
            {
                "step": "executor.follow_up_evidence_missing",
                "step_index": step_index,
                "missing": missing_follow_up,
                "message": missing_follow_up[0],
            }
        )
        return updates
    updates["draft_answer"] = answer
    updates["draft_kind"] = "executor_draft"
    updates["phase"] = "fact_extracting"
    updates["events"].append({"step": "executor.draft_answer", "handoff": "fact_extractor"})
    return updates


def _fallback_answer(state: AgentState, *, config: AgentConfig) -> str:
    """Build a best-effort answer when normal drafting cannot complete."""
    limits = config.policy.executor
    grounded = _artifact_grounded_answer(state, config=config)
    if grounded:
        return grounded
    artifacts = state.get("artifacts") or []
    if not artifacts:
        return "I completed the available steps but could not produce a detailed answer."
    lines = ["## Results", ""]
    for artifact in artifacts[: limits.fallback_artifact_limit]:
        lines.append(
            f"- {artifact.get('tool')}: {str(artifact.get('summary', ''))[: limits.fallback_summary_chars]}"
        )
    return "\n".join(lines)


def _artifact_grounded_answer(state: AgentState, *, config: AgentConfig) -> str:
    """Render a deterministic answer directly from collected artifacts."""
    limits = config.policy.executor
    artifacts = state.get("artifacts") or []
    if not artifacts:
        return ""
    lines = ["## Results from tools", ""]
    for artifact in artifacts[: limits.mechanical_artifact_limit]:
        tool_name = str(artifact.get("tool") or "tool")
        summary = str(artifact.get("summary") or "").strip()
        raw_ref = artifact.get("raw_ref") if isinstance(artifact.get("raw_ref"), dict) else {}
        if raw_ref.get("type") == "list":
            total = raw_ref.get("total")
            truncated = bool(raw_ref.get("truncated"))
            suffix = " (truncated)" if truncated else ""
            if isinstance(total, int):
                lines.append(f"- {tool_name}: {total} item(s){suffix}")
            else:
                lines.append(f"- {tool_name}:{suffix}")
        else:
            lines.append(f"- {tool_name}:")
        if summary:
            for line in summary.splitlines()[: limits.mechanical_line_limit]:
                lines.append(f"  {line}")
    return "\n".join(lines)
