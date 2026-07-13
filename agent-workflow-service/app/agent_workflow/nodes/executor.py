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
from app.agent_workflow.conversation_memory import parse_args_preview
from app.agent_workflow.deadlines import DeadlineExceeded, run_with_deadline
from app.agent_workflow.follow_up import follow_up_tool_recall_missing
from app.agent_workflow.evidence_grade import quantitative_evidence_gaps, row_evidence_gaps, step_has_row_level_evidence
from app.agent_workflow.parsing import parse_executor_action
from app.agent_workflow.parsing import normalize_tool_name
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.providers.tools import ToolProvider
from app.agent_workflow.state import AgentState, Artifact, ToolCallRecord
from app.agent_workflow.telemetry import llm_call
from app.agent_workflow.tool_arguments import (
    build_panel_data_retry_arguments,
    classify_tool_result_failure,
    normalize_tool_arguments,
)


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
    """Return successful tool names already called for the current plan step.

    Reads both artifacts and tool_calls: the summarizer can compact artifacts
    away mid-loop, but tool_calls persist, so required-tool checks must not
    forget a successful call just because its artifact was folded.
    """
    replan_id = _current_replan_id(state)
    called: set[str] = set()
    for artifact in state.get("artifacts") or []:
        raw_ref = artifact.get("raw_ref") if isinstance(artifact.get("raw_ref"), dict) else {}
        if raw_ref.get("ok") is False:
            continue
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
            and str(record.get("status") or "") == "ok"
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


def _step_stop_condition_met(state: AgentState, step_index: int, step: dict[str, Any]) -> bool:
    """Return whether a plan step's stop_condition is satisfied."""
    stop_condition = str(step.get("stop_condition") or "").strip()
    if not stop_condition:
        return True
    if step.get("require_row_level"):
        return step_has_row_level_evidence(
            state.get("artifacts") or [],
            step_index=step_index,
            replan_id=_current_replan_id(state),
        )
    return _step_has_evidence(state, step_index)


def _get_panel_data_attempted(state: AgentState) -> bool:
    """Return whether get_panel_data was invoked at least once this run."""
    for record in state.get("tool_calls") or []:
        if str(record.get("name") or "") == "get_panel_data":
            return True
    return False


def _panel_data_attempt_gap(current_step: dict[str, Any], state: AgentState) -> str | None:
    """Return a gap message when a row-level step never attempted panel data."""
    if not current_step.get("require_row_level"):
        return None
    if _get_panel_data_attempted(state):
        return None
    return "get_panel_data was not attempted for this row-level step"


def _row_level_answer_gaps(state: AgentState) -> list[str]:
    """Block premature drafts when the question needs live row data."""
    return row_evidence_gaps(
        str(state.get("user_query") or ""),
        state.get("artifacts") or [],
        plan=state.get("plan") if isinstance(state.get("plan"), dict) else None,
    )


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


def _add_guidance(updates: dict[str, Any], message: str, *, limit: int = 4) -> None:
    """Queue a correction for the next executor prompt.

    Guard vetoes and argument errors used to live only in telemetry events, so
    the model repeated the same rejected action blindly. Anything appended here
    is rendered as a high-priority "fix this first" section on the next turn.
    """
    message = str(message or "").strip()
    if not message:
        return
    guidance = list(updates.get("executor_guidance") or [])
    if message not in guidance:
        guidance.append(message)
    updates["executor_guidance"] = guidance[-limit:]


def _known_argument_values(state: AgentState) -> dict[str, Any]:
    """Map argument name -> most recently used value across the session.

    Sources, weakest to strongest (later wins): remembered conversation-memory
    slots (keyed by argument name), then arguments of successful tool calls this
    run. Purely name-matched and app-agnostic — an MCP suite that calls a
    parameter ``name`` in one tool almost always means the same thing in its
    siblings, and schema validation still runs after any fill.
    """
    known: dict[str, Any] = {}
    memory = state.get("conversation_memory") or {}
    if isinstance(memory, dict):
        for key, slot in memory.items():
            if isinstance(slot, dict) and slot.get("value") not in (None, ""):
                known[str(key)] = slot["value"]
    for record in state.get("tool_calls") or []:  # oldest -> newest; newest wins
        if str(record.get("status") or "") != "ok":
            continue
        for key, value in normalize_tool_arguments(parse_args_preview(record.get("args_preview"))).items():
            if value not in (None, "", [], {}):
                known[str(key)] = value
    plan = state.get("plan") if isinstance(state.get("plan"), dict) else {}
    dashboard = str(plan.get("dashboard") or "").strip()
    if dashboard and "name" not in known:
        known["name"] = dashboard
    return known


_ARTIFACT_SCAN_MAX_NODES = 400
_ARTIFACT_SCAN_MAX_DEPTH = 6


def _unique_field_value_from_artifacts(state: AgentState, field: str) -> Any:
    """Find one unambiguous value for ``field`` inside recent tool results.

    Required values often live in a *result* rather than any prior call's
    arguments (e.g. get_dashboard returns ``panels: [{"panel_id": 77, ...}]``
    and the next call needs ``panel_id``). Scan artifact payloads newest-first
    for scalar values under the exact key; an artifact yields a fill only when
    every occurrence agrees (a unique value) — ambiguity is never guessed at.
    """
    for artifact in reversed(state.get("artifacts") or []):
        values: list[Any] = []
        budget = _ARTIFACT_SCAN_MAX_NODES
        stack: list[tuple[Any, int]] = [
            (artifact.get("raw_ref"), 0),
            (artifact.get("source_ref"), 0),
        ]
        while stack and budget > 0:
            node, depth = stack.pop()
            budget -= 1
            if depth > _ARTIFACT_SCAN_MAX_DEPTH:
                continue
            if isinstance(node, dict):
                for key, value in node.items():
                    if str(key) == field and isinstance(value, (str, int, float)) and value not in ("",):
                        values.append(value)
                    elif isinstance(value, (dict, list)):
                        stack.append((value, depth + 1))
            elif isinstance(node, list):
                for item in node:
                    if isinstance(item, (dict, list)):
                        stack.append((item, depth + 1))
        distinct = {json.dumps(v, sort_keys=True, default=str) for v in values}
        if len(distinct) == 1:
            return values[0]
    return None


def _repair_missing_arguments(
    state: AgentState,
    *,
    arguments: dict[str, Any],
    schema: dict[str, Any],
) -> dict[str, Any]:
    """Fill missing required arguments from session-known values (by exact name).

    Returns only the filled entries. Sources, strongest first: arguments of
    prior successful calls / memory slots, then a unique same-named scalar found
    in recent tool results. This turns "call get_dashboard_tokens (missing:
    name)" or "call get_panel_data (missing: panel_id)" into an executed call
    instead of burning LLM turns asking the model to restate a value the
    session already holds. Schema validation still runs after every fill.
    """
    required = _schema_required_fields(schema)
    missing = [field for field in required if arguments.get(field) is None]
    if not missing:
        return {}
    known = _known_argument_values(state)
    filled: dict[str, Any] = {}
    for field in missing:
        if field in known:
            filled[field] = known[field]
            continue
        value = _unique_field_value_from_artifacts(state, field)
        if value is not None:
            filled[field] = value
    return filled


def _veto(updates: dict[str, Any], *, step: str, guidance: str, message: str, **fields: Any) -> dict[str, Any]:
    """Block this turn's action: queue the correction and emit the veto event.

    Every guard that rejects an action uses this one shape — the guidance string
    is what the model reads next turn, the event is what the host/UI sees.
    """
    _add_guidance(updates, guidance)
    updates["events"].append({"step": step, "message": message, **fields})
    return updates


def _schema_required_fields(schema: dict[str, Any]) -> list[str]:
    """Return the required argument names declared by a tool's input schema."""
    required = schema.get("required") if isinstance(schema, dict) else None
    return [str(item) for item in required] if isinstance(required, list) else []


_KNOWN_ACTIONS = frozenset({"search_tools", "call_tool", "finish_step", "draft_answer"})


def _normalize_tool_name_action(
    action: dict[str, Any],
    action_type: str,
    candidate_tools: list[dict[str, Any]],
) -> tuple[dict[str, Any], str, bool]:
    """Recover ``{"action": "<tool name>", ...}`` as a proper call_tool action.

    Models regularly conflate the action field with the tool to call (e.g.
    ``{"action":"search_panels","query":"x"}``). Left alone that falls through
    to the draft path and the run produces zero tool calls. When the "action"
    names a known candidate tool, rewrite it to call_tool with the remaining
    keys as arguments. Returns (action, action_type, recovered?).
    """
    if action_type in _KNOWN_ACTIONS or not action_type:
        return action, action_type, False
    for candidate in candidate_tools:
        name = str(candidate.get("name") or "")
        if name.lower() == action_type:
            provided = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
            # Loose keys ride along as arguments ({"action":"search_panels","query":"x"}
            # means arguments={"query":"x"}); an explicit arguments dict wins on conflict.
            extras = {k: v for k, v in action.items() if k not in {"action", "arguments", "name", "answer"}}
            return {"action": "call_tool", "name": name, "arguments": {**extras, **provided}}, "call_tool", True
    return action, action_type, False


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


def _incomplete_evidence_result(
    *,
    state: AgentState,
    updates: dict[str, Any],
    iteration: dict[str, Any],
    reason: str,
    missing: list[str],
    step_index: int | None = None,
) -> dict[str, Any]:
    """End honestly when required evidence could not be gathered."""
    missing = [str(item).strip() for item in missing if str(item).strip()]
    missing_text = "\n".join(f"- {item}" for item in missing) if missing else "- Required evidence was not gathered."
    answer = (
        "I could not complete this request with reliable evidence.\n\n"
        f"Missing evidence:\n{missing_text}\n\n"
        "I am not going to infer or fabricate the final answer from metadata."
    )
    error = f"Incomplete evidence: {reason}"
    updates["phase"] = "done"
    updates["final_answer"] = answer
    updates["draft_answer"] = answer
    updates["draft_kind"] = "mechanical"
    updates["error"] = state.get("error") or error
    updates["iteration"] = iteration
    updates["events"].append(
        {
            "step": "executor.incomplete_evidence",
            "step_index": step_index,
            "reason": reason,
            "missing": missing,
            "message": error,
        }
    )
    return updates


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


def _tool_policy_sets(config: AgentConfig) -> tuple[set[str], set[str]]:
    """Return the (allowlist, denylist) name sets from the tool policy."""
    allowlist = {item for item in (config.policy.tools.allowlist or []) if item}
    denylist = {item for item in (config.policy.tools.denylist or []) if item}
    return allowlist, denylist


def _is_tool_allowed(tool_name: str, *, config: AgentConfig) -> bool:
    """Return whether the configured tool policy allows this tool."""
    allowlist, denylist = _tool_policy_sets(config)
    if tool_name in denylist:
        return False
    if not allowlist:
        return True
    return tool_name in allowlist


def _filter_candidates_by_policy(candidates: list[dict[str, Any]], *, config: AgentConfig) -> list[dict[str, Any]]:
    """Remove discovered tools blocked by allowlist or denylist policy."""
    # Build the policy sets once per filter pass, not once per candidate.
    allowlist, denylist = _tool_policy_sets(config)
    filtered = []
    for candidate in candidates:
        tool_name = str(candidate.get("name") or "")
        if not tool_name or tool_name in denylist:
            continue
        if allowlist and tool_name not in allowlist:
            continue
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
    from app.agent_workflow.evidence_grade import row_evidence_gaps

    steps = (state.get("plan") or {}).get("steps") or []
    if not steps:
        return False
    step_index = int(state.get("current_step_index") or 0)
    if step_index >= len(steps):
        return bool(
            row_evidence_gaps(
                str(state.get("user_query") or ""),
                state.get("artifacts") or [],
                plan=state.get("plan") if isinstance(state.get("plan"), dict) else None,
            )
        )
    current_step = steps[step_index]
    required = _required_tools_for_step(config, current_step)
    called = _called_tools_for_step(state, step_index) | _called_tools_for_run(state)
    if required - called:
        return True
    stop_condition = str(current_step.get("stop_condition") or "").strip()
    if stop_condition and not _step_stop_condition_met(state, step_index, current_step):
        return True
    if current_step.get("require_row_level") and not step_has_row_level_evidence(
        state.get("artifacts") or [],
        step_index=step_index,
        replan_id=_current_replan_id(state),
    ):
        return True
    if row_evidence_gaps(
        str(state.get("user_query") or ""),
        state.get("artifacts") or [],
        plan=state.get("plan") if isinstance(state.get("plan"), dict) else None,
    ):
        return True
    return step_index < len(steps) - 1


def _step_is_complete(state: AgentState, config: AgentConfig, *, step_index: int, step: dict[str, Any]) -> bool:
    """Return whether a plan step's required work is already satisfied."""
    required = _required_tools_for_step(config, step)
    called = _called_tools_for_step(state, step_index) | _called_tools_for_run(state)
    if required - called:
        return False
    stop_condition = str(step.get("stop_condition") or "").strip()
    if stop_condition and not _step_stop_condition_met(state, step_index, step):
        return False
    if step.get("require_row_level") and not step_has_row_level_evidence(
        state.get("artifacts") or [],
        step_index=step_index,
        replan_id=_current_replan_id(state),
    ):
        return False
    return True


def _auto_advance_completed_steps(state: AgentState, config: AgentConfig) -> dict[str, Any] | None:
    """Advance past steps whose required tools and stop conditions are already met."""
    steps = (state.get("plan") or {}).get("steps") or []
    if not steps:
        return None
    step_index = int(state.get("current_step_index") or 0)
    if step_index >= len(steps):
        return None

    advanced_from = step_index
    while step_index < len(steps):
        current_step = steps[step_index]
        if not _step_is_complete(state, config, step_index=step_index, step=current_step):
            break
        if step_index >= len(steps) - 1:
            break
        step_index += 1

    if step_index == advanced_from:
        return None

    return {
        "current_step_index": step_index,
        "candidate_tools": [],
        "events": [
            {
                "step": "executor.auto_advance",
                "from_step": advanced_from,
                "to_step": step_index,
                "message": f"Advanced to plan step {step_index + 1} because prior step(s) were already complete.",
            }
        ],
    }


def _row_gaps_block_handoff(state: AgentState) -> list[str]:
    """Return row-evidence gaps that must block synthesis handoff."""
    return row_evidence_gaps(
        str(state.get("user_query") or ""),
        state.get("artifacts") or [],
        plan=state.get("plan") if isinstance(state.get("plan"), dict) else None,
    )


def _handoff_to_fact_extracting(
    *,
    state: AgentState,
    updates: dict[str, Any],
    iteration: dict[str, Any],
    reason: str,
    step_index: int | None = None,
    extra_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Move to fact extraction only when row-evidence requirements are satisfied."""
    missing = _row_gaps_block_handoff(state)
    events = list(updates.get("events") or [])
    if extra_events:
        events.extend(extra_events)
    updates["events"] = events
    updates["iteration"] = iteration
    if missing:
        return _incomplete_evidence_result(
            state=state,
            updates=updates,
            iteration=iteration,
            reason=reason,
            missing=missing,
            step_index=step_index,
        )
    updates["phase"] = "fact_extracting"
    return updates


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
    step_index: int,
) -> dict[str, Any]:
    """Record invalid tool arguments into workflow state or telemetry.

    The record carries step/replan ids so the duplicate-call guard sees repeated
    identical *invalid* attempts too — without this, a greedy model that keeps
    emitting the same broken call burns the entire iteration budget re-failing
    validation instead of being coerced to finish/advance.
    """
    record: ToolCallRecord = {
        "name": tool_name,
        "args_preview": json.dumps(arguments)[:300],
        "status": "invalid_args",
        "latency_ms": 0,
        "error": "; ".join(errors),
        "step_index": step_index,
        "replan_id": _current_replan_id(state),
    }
    tool_calls = list(state.get("tool_calls") or [])
    tool_calls.append(record)
    tool_calls = _prune_tool_calls(tool_calls, config=config)
    iteration["tool_calls"] = int(iteration.get("tool_calls") or 0) + 1
    updates["tool_calls"] = tool_calls
    updates["iteration"] = iteration
    _add_guidance(
        updates,
        f"Your last call to {tool_name} was rejected: {record['error']}. "
        f"Call it again with every required argument filled from prior tool results or the user request — do not retry unchanged.",
    )
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
    panel_retry: bool = True,
) -> dict[str, Any]:
    """Execute a tool call and fold the result into state updates.

    No destructive gating here — callers are either non-destructive paths or the
    approval node executing an explicitly approved call.
    """
    arguments = normalize_tool_arguments(arguments)
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

    payload_error = classify_tool_result_failure(result)
    if payload_error:
        status = "failed"
        error = payload_error

    if (
        panel_retry
        and tool_name == "get_panel_data"
        and status == "failed"
        and isinstance(result, dict)
    ):
        retry_args = build_panel_data_retry_arguments(state, arguments, result)
        if retry_args:
            called_signatures, _ = _step_call_signatures_and_count(state, step_index)
            retry_signature = (tool_name, json.dumps(retry_args)[:300])
            if retry_signature not in called_signatures:
                updates["events"].append(
                    {
                        "step": "executor.panel_data_retry",
                        "tool": tool_name,
                        "message": "Retrying get_panel_data with token defaults for open/missing filters.",
                        "filled_tokens": sorted((retry_args.get("panel_tokens") or {}).keys()),
                    }
                )
                return _run_tool_and_record(
                    state=state,
                    config=config,
                    tools=tools,
                    tool_name=tool_name,
                    arguments=retry_args,
                    updates=updates,
                    iteration=iteration,
                    step_index=step_index,
                    step_query=step_query,
                    on_tool_call=on_tool_call,
                    on_artifact=on_artifact,
                    panel_retry=False,
                )

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
            "result_ok": status == "ok",
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
        return _handoff_to_fact_extracting(
            state=state,
            updates={"iteration": iteration, "events": []},
            iteration=iteration,
            reason="executor iteration limit",
            extra_events=[{"step": "executor.iteration_limit", "handoff": "fact_extractor"}],
        )

    auto_updates = _auto_advance_completed_steps(state, config)
    if auto_updates:
        state = {**state, **auto_updates}

    # Generic early stop: once tool work stops producing useful new evidence,
    # stop exploring and answer with what we have rather than burning the budget.
    stalled, iteration = _update_no_progress(state, iteration, config)
    if stalled and not _plan_steps_incomplete(state, config):
        return _handoff_to_fact_extracting(
            state=state,
            updates={"iteration": iteration, "events": []},
            iteration=iteration,
            reason="executor no-progress stop",
            extra_events=[
                {
                    "step": "executor.no_progress_stop",
                    "handoff": "fact_extractor",
                    "no_progress_turns": int(iteration.get("no_progress_turns") or 0),
                    "useful_artifacts": int(iteration.get("useful_artifacts_seen") or 0),
                }
            ],
        )

    plan = state.get("plan") or {}
    steps = plan.get("steps") or []
    step_index = int(state.get("current_step_index") or 0)
    if step_index >= len(steps):
        return _handoff_to_fact_extracting(
            state=state,
            updates={"iteration": iteration, "events": auto_updates.get("events", []) if auto_updates else []},
            iteration=iteration,
            reason="executor completed all plan steps",
            extra_events=[{"step": "executor.completed_steps", "handoff": "fact_extractor"}],
        )

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
            "\n\nReturn exactly ONE JSON object. \"action\" must be one of: search_tools, call_tool, finish_step, draft_answer"
            " — never a tool name (tool names go in \"name\"):\n"
            '{"action":"search_tools","query":"..."}\n'
            '{"action":"call_tool","name":"tool_name","arguments":{...}}\n'
            '{"action":"finish_step"}\n'
            '{"action":"draft_answer","answer":"..."}\n'
            'Example — to run search_panels: {"action":"call_tool","name":"search_panels","arguments":{"query":"..."}}'
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
        return _handoff_to_fact_extracting(
            state=state,
            updates={"iteration": iteration, "error": str(exc), "events": []},
            iteration=iteration,
            reason="executor timeout",
            extra_events=[{"step": "executor.timeout", "error": str(exc), "handoff": "fact_extractor"}],
        )
    if action is None:
        action = parse_executor_action(raw)
    action_type = str(action.get("action") or "").lower()

    # In native mode this exact filter already ran for native_candidates; reuse it.
    candidate_tools = (
        native_candidates
        if native_mode
        else _filter_candidates_by_policy(list(state.get("candidate_tools") or []), config=config)
    )
    # Models often put a tool name straight into the action field
    # ({"action":"search_panels","query":...}); without this normalization the
    # turn falls through to the draft path and no tool ever runs.
    action, action_type, recovered_tool_action = _normalize_tool_name_action(action, action_type, candidate_tools)
    called_this_step = _called_tools_for_step(state, step_index)
    # Guidance is rebuilt every turn: a clean turn clears last turn's corrections,
    # and any veto/error below re-adds what the model must fix next turn.
    updates: dict[str, Any] = {"iteration": iteration, "phase": "executing", "executor_guidance": []}
    if auto_updates:
        updates.update({k: v for k, v in auto_updates.items() if k != "events"})
        if auto_updates.get("events"):
            prefetch_events = list(auto_updates.get("events") or []) + prefetch_events
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
    if recovered_tool_action:
        updates["events"].append(
            {
                "step": "executor.action_recovered",
                "tool": action.get("name"),
                "message": f"Model used the tool name as the action; recovered as call_tool({action.get('name')}).",
            }
        )

    if action_type == "search_tools" and candidate_tools:
        # _search_repeat_counter mutates `iteration` in place, which is already
        # stored in updates["iteration"] above.
        repeat_count = _search_repeat_counter(iteration, step_index=step_index)
        if repeat_count == 1:
            return _veto(
                updates,
                step="executor.tool_candidates_available",
                guidance=(
                    "Do not call search_tools again: candidate tools are already listed in your context. "
                    "Choose call_tool with schema-valid arguments (fill every required argument from prior results or the user request)."
                ),
                message="Candidate tools are already available; select call_tool with schema-valid arguments.",
                tool_count=len(candidate_tools),
            )

        # Only force a call the schema allows: a tool with unmet required
        # arguments would just fail validation and burn the turn (e.g. forcing
        # get_panel_data with {} when panel_id is required).
        forced = None
        if repeat_count == 2 and not called_this_step:
            forced = next(
                (c for c in candidate_tools if not _schema_required_fields(_schema_for_tool(str(c.get("name") or ""), candidate_tools))),
                None,
            )
        if forced is not None:
            action_type = "call_tool"
            action = {"action": "call_tool", "name": forced.get("name"), "arguments": {}}
            updates["events"].append(
                {
                    "step": "executor.search_loop_breaker",
                    "message": f"Repeated search_tools with candidates; forcing call_tool({forced.get('name')}).",
                }
            )
        elif repeat_count == 2 and not called_this_step:
            top = candidate_tools[0]
            required = _schema_required_fields(_schema_for_tool(str(top.get("name") or ""), candidate_tools))
            return _veto(
                updates,
                step="executor.search_loop_breaker",
                guidance=(
                    f"Stop searching. Call {top.get('name')} with its required argument(s) "
                    f"{', '.join(required)} filled in (use values from prior tool results or the user request)."
                ),
                message=(
                    f"Repeated search_tools; every candidate needs required arguments "
                    f"(e.g. {top.get('name')}: {', '.join(required)}) — asking the model to fill them."
                ),
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

    if action_type == "call_tool":
        tool_name = str(action.get("name") or "")
        # Compare the post-injection argument preview (the same shape stored on the
        # tool-call record) so the same tool with *different* arguments is allowed —
        # e.g. a second get_panel_data with different panel_tokens — while an exact
        # repeat is skipped. The per-step budget counts total calls, not distinct
        # tool names, so a re-explore step gets a fresh budget of its own.
        proposed_args = normalize_tool_arguments(
            action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
        )
        call_schema = _schema_for_tool(tool_name, candidate_tools)
        injected_args = _apply_argument_injection(
            tool_name=tool_name,
            arguments=proposed_args,
            schema=call_schema,
            runtime_context=dict(state.get("runtime_context") or {}),
            config=config,
        )
        # Deterministic repair before the dedup signature: required args the
        # session already knows (prior calls / memory slots) are filled by name
        # instead of burning an LLM turn on a guaranteed validation failure —
        # and the signature then reflects the call as it will actually run.
        repaired_fill = _repair_missing_arguments(state, arguments=injected_args, schema=call_schema)
        if repaired_fill:
            injected_args = {**injected_args, **repaired_fill}
        call_signature = (tool_name, json.dumps(injected_args)[:300])
        called_signatures, step_call_count = _step_call_signatures_and_count(state, step_index)
        max_per_step = config.policy.max_tool_calls_per_step
        if call_signature in called_signatures:
            steps = (state.get("plan") or {}).get("steps") or []
            current_step = steps[step_index] if 0 <= step_index < len(steps) else {}
            if current_step.get("require_row_level") and not _step_stop_condition_met(
                state, step_index, current_step
            ):
                if _finish_is_deadlocked(iteration, config):
                    missing = [
                        "Row-level tool results were not returned — prior get_panel_data calls did not produce rows."
                    ]
                    return _incomplete_evidence_result(
                        state=state,
                        updates=updates,
                        iteration=iteration,
                        reason="re-explore could not obtain row-level panel data",
                        missing=missing,
                        step_index=step_index,
                    )
                return _veto(
                    updates,
                    step="executor.duplicate_panel_data_no_rows",
                    guidance=(
                        f"Prior {tool_name} call did not return rows. Pass complete panel_tokens "
                        "(include open filters like row and labs from get_dashboard_tokens defaults) "
                        "before repeating the same call."
                    ),
                    message="Duplicate get_panel_data with no row-level evidence; try different panel_tokens.",
                    tool=tool_name,
                    step_index=step_index,
                )
            action_type = "finish_step"
            _add_guidance(
                updates,
                f"You already called {tool_name} with those exact arguments this step; its result is in your context. "
                "Use a different tool/arguments or finish the step — do not repeat the call.",
            )
            updates["events"].append(
                {
                    "step": "executor.duplicate_tool_skipped",
                    "tool": tool_name,
                    "message": "Tool was already called with identical arguments for this step; finishing instead of repeating it.",
                }
            )
        elif step_call_count >= max_per_step:
            action_type = "finish_step"
            _add_guidance(updates, "Tool budget for this step is spent; finish the step or draft from the evidence you have.")
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
                step_index=step_index,
            )
        candidate_names = {str(tool.get("name") or "") for tool in candidate_tools}
        if candidate_tools and tool_name not in candidate_names:
            errors = [f"tool was not discovered for this step: {tool_name}"]
        else:
            # The guard block already injected runtime-context arguments and
            # applied the deterministic repair; reuse instead of recomputing.
            arguments = injected_args
            if repaired_fill:
                updates["events"].append(
                    {
                        "step": "executor.arguments_repaired",
                        "tool": tool_name,
                        "filled": {k: str(v)[:120] for k, v in repaired_fill.items()},
                        "message": (
                            f"Filled missing required argument(s) for {tool_name} from session context: "
                            f"{', '.join(sorted(repaired_fill))}"
                        ),
                    }
                )
            errors = _validate_tool_arguments(tool_name, arguments, call_schema)
        if errors:
            return _record_invalid_tool_arguments(
                state=state,
                config=config,
                updates=updates,
                iteration=iteration,
                tool_name=tool_name,
                arguments=arguments,
                errors=errors,
                step_index=step_index,
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
        # max_no_progress_turns). Past that, unresolved guards become an honest
        # incomplete-evidence result instead of a fabricated best effort.
        deadlocked = _finish_is_deadlocked(iteration, config)
        if not deadlocked:
            panel_gap = _panel_data_attempt_gap(current_step, state)
            if panel_gap:
                return _veto(
                    updates,
                    step="executor.panel_data_not_attempted",
                    guidance=(
                        "Call get_panel_data with panel_id from get_dashboard and panel_tokens "
                        "(site, labs, row, availablepowerrange) before finishing this step."
                    ),
                    message=panel_gap,
                    step_index=step_index,
                    missing=[panel_gap],
                )
            missing_follow_up = follow_up_tool_recall_missing(state)
            if missing_follow_up:
                return _veto(
                    updates,
                    step="executor.follow_up_evidence_missing",
                    guidance=f"{missing_follow_up[0]}. Pick a tool from the candidate list and call it with schema-valid arguments now.",
                    message=missing_follow_up[0],
                    step_index=step_index,
                    missing=missing_follow_up,
                )
            stop_condition = str(current_step.get("stop_condition") or "").strip()
            if stop_condition and not _step_stop_condition_met(state, step_index, current_step):
                return _veto(
                    updates,
                    step="executor.stop_condition_unmet",
                    guidance=f"Do not finish this step yet — its stop condition is unmet: {stop_condition}. Call a tool to gather that evidence.",
                    message=(
                        f"Stop condition not met yet: {stop_condition}. "
                        "Call tools and gather evidence before finish_step."
                    ),
                    step_index=step_index,
                    stop_condition=stop_condition,
                )
            required_tools = _required_tools_for_step(config, current_step)
            # called_this_step was computed at turn start and state is unchanged.
            called = called_this_step | _called_tools_for_run(state)
            missing_required = sorted(required_tools - called)
            if missing_required:
                return _veto(
                    updates,
                    step="executor.required_tools_missing",
                    guidance=f"Call {', '.join(missing_required)} (with schema-valid arguments) before finishing this step.",
                    message=f"Required tools not yet called: {', '.join(missing_required)}",
                    step_index=step_index,
                    required_tools=missing_required,
                )
        else:
            missing: list[str] = []
            missing.extend(follow_up_tool_recall_missing(state))
            panel_gap = _panel_data_attempt_gap(current_step, state)
            if panel_gap:
                missing.append(panel_gap)
            stop_condition = str(current_step.get("stop_condition") or "").strip()
            if stop_condition and not _step_stop_condition_met(state, step_index, current_step):
                missing.append(f"Stop condition not met: {stop_condition}")
            required_tools = _required_tools_for_step(config, current_step)
            called = called_this_step | _called_tools_for_run(state)
            missing_required = sorted(required_tools - called)
            if missing_required:
                missing.append(f"Required tools not successfully called: {', '.join(missing_required)}")
            if missing:
                return _incomplete_evidence_result(
                    state=state,
                    updates=updates,
                    iteration=iteration,
                    reason="step guards remained unmet after the no-progress budget",
                    missing=missing,
                    step_index=step_index,
                )
            updates["events"].append(
                {
                    "step": "executor.finish_deadlock_break",
                    "step_index": step_index,
                    "no_progress_turns": int(iteration.get("no_progress_turns") or 0),
                    "message": "No guard remains unmet; advancing after no-progress deadlock.",
                }
            )
        next_index = step_index + 1
        # Each step gets a fresh stall budget so a deadlock on one step does not
        # immediately trip the no-progress stop on the next. (iteration is the
        # same object already stored in updates["iteration"].)
        iteration["no_progress_turns"] = 0
        updates["current_step_index"] = next_index
        updates["candidate_tools"] = []
        updates["events"].append({"step": "executor.finish_step", "step_index": step_index})
        if next_index >= len(steps):
            return _handoff_to_fact_extracting(
                state=state,
                updates=updates,
                iteration=iteration,
                reason="executor finished final plan step",
                step_index=step_index,
                extra_events=[{"step": "executor.completed_steps", "handoff": "fact_extractor"}],
            )
        return updates

    # An unrecognized JSON action that isn't a candidate tool either must not
    # silently become a draft (that is how runs ended with zero tool calls).
    # Tell the model the valid actions and retry; the deadlock cap bounds this.
    if action_type not in _KNOWN_ACTIONS and action_type and not _finish_is_deadlocked(iteration, config):
        tool_names = ", ".join(str(c.get("name") or "") for c in candidate_tools[:6]) or "none discovered yet"
        return _veto(
            updates,
            step="executor.unknown_action",
            guidance=(
                f"'{action_type}' is not a valid action. Reply with one of: search_tools, call_tool, finish_step, draft_answer. "
                f"To run a tool use {{\"action\":\"call_tool\",\"name\":\"<tool>\",\"arguments\":{{...}}}} (candidates: {tool_names})."
            ),
            message=f"Unknown action '{action_type}'; asking the model to choose a valid one.",
            action=action_type,
        )

    answer = str(action.get("answer") or raw).strip()
    missing_follow_up = follow_up_tool_recall_missing(state)
    missing_row_level = _row_level_answer_gaps(state)
    # Same arbitration as finish_step: the veto may block a premature draft, but
    # once the step is deadlocked (no new evidence for max_no_progress_turns)
    # unresolved evidence becomes a terminal incomplete-evidence result.
    if missing_follow_up and not _finish_is_deadlocked(iteration, config):
        return _veto(
            updates,
            step="executor.follow_up_evidence_missing",
            guidance=f"{missing_follow_up[0]}. Do not draft an answer yet — pick a tool from the candidate list and call it with schema-valid arguments.",
            message=missing_follow_up[0],
            step_index=step_index,
            missing=missing_follow_up,
        )
    if missing_row_level and not _finish_is_deadlocked(iteration, config):
        row_guidance = (
            f"{missing_row_level[0]} Call a tool that returns row-level results "
            "(for example get_panel_data with panel_id and panel_tokens) before draft_answer."
        )
        if current_step.get("require_row_level"):
            row_guidance = (
                f"{missing_row_level[0]} You are on step '{current_step.get('title', 'Query panel data')}'. "
                "Call get_panel_data with panel_id from get_dashboard and panel_tokens for site/labs/row/"
                "availablepowerrange from the user request. Do not draft_answer until rows return."
            )
        return _veto(
            updates,
            step="executor.row_level_evidence_missing",
            guidance=row_guidance,
            message=missing_row_level[0],
            step_index=step_index,
            missing=missing_row_level,
        )
    if missing_follow_up or missing_row_level:
        return _incomplete_evidence_result(
            state=state,
            updates=updates,
            iteration=iteration,
            reason="draft evidence guards remained unmet after the no-progress budget",
            missing=list(missing_follow_up) + list(missing_row_level),
            step_index=step_index,
        )
    updates["draft_answer"] = answer
    updates["draft_kind"] = "executor_draft"
    return _handoff_to_fact_extracting(
        state=state,
        updates=updates,
        iteration=iteration,
        reason="executor draft answer",
        step_index=step_index,
        extra_events=[{"step": "executor.draft_answer", "handoff": "fact_extractor"}],
    )


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
