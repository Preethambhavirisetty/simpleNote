from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from app.agent_workflow.state import AgentState, Artifact


@dataclass
class RunRequest:
    """Normalized request passed to the engine."""
    query: str
    session_id: str = ""
    history: list[dict[str, Any]] = field(default_factory=list)
    runtime_context: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunResult:
    """Final result returned by sync and resume calls."""
    answer: str
    review: dict[str, Any]
    artifacts: list[Artifact]
    tool_calls: list[dict[str, Any]]
    events: list[dict[str, Any]]
    error: str | None = None
    # Set when the run paused on a destructive-approval interrupt; resume with
    # AgentEngine.resume(thread_id, approved=...).
    pending_approval: dict[str, Any] | None = None
    thread_id: str = ""


@dataclass
class HostCallbacks:
    """Optional hooks for hosts to observe workflow activity."""
    on_plan: Callable[[dict[str, Any]], None] | None = None
    on_tool_search: Callable[[str, list[dict[str, Any]]], None] | None = None
    on_tool_call: Callable[[str, dict[str, Any], Any], None] | None = None
    on_artifact: Callable[[Artifact], None] | None = None
    on_review: Callable[[dict[str, Any]], None] | None = None
    on_destructive_action: Callable[[str, dict[str, Any]], bool] | None = None
    on_event: Callable[[dict[str, Any]], None] | None = None


def map_graph_update(update: dict[str, Any], prev: AgentState) -> list[dict[str, Any]]:
    """Translate LangGraph node output into host events."""
    # Nodes store durable-ish workflow events in state. This function turns
    # those internal events into API/SSE events that clients can render.
    events: list[dict[str, Any]] = []
    merged: AgentState = {**prev, **update}

    if "plan" in update and update.get("plan"):
        plan = update["plan"]
        steps = plan.get("steps") or []
        events.append(
            {
                "type": "plan",
                "goal": plan.get("goal", ""),
                "steps": [s.get("title", "") for s in steps],
                "message": "Plan created",
            }
        )

    for entry in update.get("events") or []:
        step = entry.get("step", "")
        if step == "executor.action":
            events.append(
                {
                    "type": "debug",
                    "message": (
                        f"Executor turn {entry.get('executor_turn')}: "
                        f"action={entry.get('action')} "
                        f"(plan step {int(entry.get('step_index', 0)) + 1}: {entry.get('step_title', '')})"
                    ),
                }
            )
        elif step == "executor.search_tools":
            tools = entry.get("tools") or []
            events.append(
                {
                    "type": "agent_activity",
                    "phase": "running",
                    "tool": "tool_catalog_search",
                    "label": f"Searching tool catalog: {entry.get('query', '')}",
                    "query": entry.get("query", ""),
                    "tool_count": entry.get("tool_count", len(tools)),
                    "tools": tools,
                }
            )
        elif step in {
            "executor.tool_candidates_available",
            "executor.duplicate_tool_skipped",
            "executor.tool_limit_reached",
            "executor.search_loop_breaker",
            "executor.required_tools_missing",
            "executor.tool_policy_blocked",
        }:
            events.append({"type": "debug", "message": entry.get("message", "")})
        elif step == "executor.tool_args_invalid":
            events.append(
                {
                    "type": "debug",
                    "message": f"Invalid arguments for {entry.get('tool')}: {entry.get('error')}",
                }
            )
        elif step == "executor.approval_required":
            events.append(
                {
                    "type": "agent_activity",
                    "phase": "blocked",
                    "tool": entry.get("tool", "tool"),
                    "label": f"Approval required for {entry.get('tool')}",
                }
            )
        elif step in {"executor.destructive_denied", "executor.destructive_skipped", "approval.denied"}:
            events.append(
                {
                    "type": "debug",
                    "message": f"Destructive tool {entry.get('tool')} not executed ({step.rsplit('.', 1)[-1]})",
                }
            )
        elif step == "approval.approved":
            events.append(
                {
                    "type": "debug",
                    "message": f"Destructive tool {entry.get('tool')} approved; executing",
                }
            )
        elif step == "executor.finish_step":
            events.append(
                {
                    "type": "debug",
                    "message": f"Finished plan step {int(entry.get('step_index', 0)) + 1}",
                }
            )
        elif step == "executor.call_tool":
            tool_name = str(entry.get("tool") or "tool")
            status = str(entry.get("status") or "error")
            arguments = entry.get("arguments") if isinstance(entry.get("arguments"), dict) else {}
            error_text = str(entry.get("error") or "").strip()
            events.append(
                {
                    "type": "agent_activity",
                    "phase": "completed" if status == "ok" else "failed",
                    "tool": tool_name,
                    "label": f"Tool call: {tool_name}" + (" succeeded" if status == "ok" else " failed"),
                    "input_preview": json.dumps(arguments, default=str)[:800] if arguments else "",
                    "result_preview": error_text if error_text else "Completed successfully",
                    "error": error_text or None,
                    "status": status,
                }
            )
        elif step == "reviewer.completed":
            verdict = str(entry.get("verdict") or "UNKNOWN")
            issues = entry.get("issues") or []
            required = entry.get("required_changes") or []
            missing = entry.get("missing_evidence") or []
            summary_parts = [f"Review: {verdict}"]
            if issues:
                summary_parts.append(f"{len(issues)} issue(s)")
            if required:
                summary_parts.append(f"{len(required)} change(s) required")
            events.append(
                {
                    "type": "review",
                    "verdict": verdict,
                    "issues": issues,
                    "missing_evidence": missing,
                    "required_changes": required,
                    "artifact_count": entry.get("artifact_count", 0),
                    "tool_call_count": entry.get("tool_call_count", 0),
                    "draft_answer_preview": entry.get("draft_answer_preview", ""),
                }
            )
            events.append(
                {
                    "type": "agent_activity",
                    "phase": "review",
                    "label": " · ".join(summary_parts),
                    "verdict": verdict,
                    "issues": issues,
                    "missing_evidence": missing,
                    "required_changes": required,
                }
            )

    if update.get("error") and merged.get("phase") == "reviewing":
        events.append({"type": "debug", "message": f"Error: {update['error']}"})

    if merged.get("final_answer") and merged.get("phase") == "done":
        events.append(
            {
                "type": "done",
                "answer": merged.get("final_answer"),
                "review": merged.get("review"),
                "artifact_count": len(merged.get("artifacts") or []),
                "tool_call_count": len(merged.get("tool_calls") or []),
                "error": merged.get("error"),
            }
        )
    return events
