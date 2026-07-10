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


def map_graph_update(update: dict[str, Any], prev: AgentState, *, node_name: str | None = None) -> list[dict[str, Any]]:
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
        elif step == "executor.stop_condition_unmet":
            events.append(
                {
                    "type": "agent_activity",
                    "phase": "running",
                    "label": entry.get("message") or "Stop condition not met; gathering more evidence",
                    "stop_condition": entry.get("stop_condition"),
                }
            )
        elif step == "executor.follow_up_evidence_missing":
            events.append(
                {
                    "type": "agent_activity",
                    "phase": "blocked",
                    "label": entry.get("message") or "Follow-up requires fresh tool evidence",
                    "missing": entry.get("missing") or [],
                }
            )
        elif step in {
            "executor.tool_candidates_available",
            "executor.duplicate_tool_skipped",
            "executor.tool_limit_reached",
            "executor.search_loop_breaker",
            "executor.required_tools_missing",
            "executor.tool_policy_blocked",
            "executor.finish_deadlock_break",
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
        elif step == "executor.completed_steps":
            events.append(
                {
                    "type": "agent_activity",
                    "phase": "completed",
                    "label": "Execution complete; extracting facts",
                    "handoff": entry.get("handoff"),
                }
            )
        elif step == "fact_extractor.completed":
            tools = entry.get("tools") or []
            preview = entry.get("preview") or []
            tool_counts = entry.get("tool_fact_counts") or {}
            fact_count = entry.get("fact_count", 0)
            artifact_count = entry.get("artifact_count", 0)
            if entry.get("used_draft_fallback"):
                label = "Extractor: no tool evidence collected — using the executor draft as a low-confidence fact"
            elif not fact_count:
                label = f"Extractor: no facts could be distilled from {artifact_count} tool result(s)"
            else:
                per_tool = ", ".join(f"{name} ({count})" for name, count in sorted(tool_counts.items())) or ", ".join(tools)
                label = f"Extractor: distilled {fact_count} fact(s) from {artifact_count} tool result(s) — {per_tool}"
                if preview:
                    label += f" | e.g. “{preview[0]}”"
            events.append(
                {
                    "type": "agent_activity",
                    "phase": "fact_extraction",
                    "label": label,
                    "fact_count": fact_count,
                    "artifact_count": artifact_count,
                    "truncated_source_count": entry.get("truncated_source_count", 0),
                    "tools": tools,
                    "preview": preview,
                }
            )
        elif step == "executor.no_progress_stop":
            events.append(
                {
                    "type": "agent_activity",
                    "phase": "completed",
                    "label": (
                        f"No new evidence in the last {entry.get('no_progress_turns', 0)} turn(s); "
                        f"answering with {entry.get('useful_artifacts', 0)} useful result(s)"
                    ),
                    "handoff": entry.get("handoff"),
                }
            )
        elif step == "summarizer.completed":
            events.append(
                {
                    "type": "agent_activity",
                    "phase": "running",
                    "label": f"Compacted memory: folded {entry.get('folded_count', 0)} artifact(s) into a running summary",
                    "answer_chars": entry.get("summary_chars", 0),
                }
            )
        elif step in {"summarizer.timeout", "summarizer.noop"}:
            events.append({"type": "debug", "message": f"Memory compaction {step.rsplit('.', 1)[-1]}: {entry.get('error') or entry.get('reason') or ''}"})
        elif step == "synthesizer.completed":
            events.append(
                {
                    "type": "agent_activity",
                    "phase": "synthesis",
                    "label": f"Synthesized draft from {entry.get('fact_count', 0)} fact(s)",
                    "fact_count": entry.get("fact_count", 0),
                    "answer_chars": entry.get("answer_chars", 0),
                }
            )
        elif step == "synthesizer.skipped":
            events.append(
                {
                    "type": "agent_activity",
                    "phase": "synthesis",
                    "label": f"Synthesis skipped ({entry.get('reason', 'skipped')}); using existing draft",
                    "answer_chars": entry.get("answer_chars", 0),
                }
            )
        elif step == "synthesizer.fallback":
            events.append(
                {
                    "type": "agent_activity",
                    "phase": "synthesis",
                    "label": f"Synthesis fell back to a deterministic answer ({entry.get('reason', 'fallback')})",
                    "fact_count": entry.get("fact_count", 0),
                    "answer_chars": entry.get("answer_chars", 0),
                }
            )
        elif step == "synthesizer.timeout":
            events.append({"type": "debug", "message": f"Synthesis timed out: {entry.get('error')}"})
        elif step == "reviewer.parse_failed":
            events.append({"type": "debug", "message": "Reviewer output was not parseable; defaulting to REVISE"})
        elif step == "reviewer.re_explore":
            missing = entry.get("missing_evidence") or []
            events.append(
                {
                    "type": "agent_activity",
                    "phase": "running",
                    "label": "Reviewer requested more exploration",
                    "explore_cycles": entry.get("explore_cycles", 0),
                    "missing_evidence": missing,
                }
            )
        elif step == "finalizer.unexpected_phase":
            events.append({"type": "debug", "message": f"Finalizer reached an unexpected phase ({entry.get('phase', '')}); returning best-effort answer"})
        elif step == "revision.completed":
            events.append(
                {
                    "type": "agent_activity",
                    "phase": "revision",
                    "label": "Revised draft using reviewer issues",
                    "answer_chars": entry.get("answer_chars", 0),
                }
            )
        elif step in {"revision.timeout", "revision.limit_reached"}:
            events.append({"type": "debug", "message": f"Revision stopped: {entry.get('error') or step}"})
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
            # Summary-only activity ping: the full issue/missing/change lists ride
            # on the `review` event above, so they are not repeated here (emitting
            # both rendered every verdict twice in the activity feed).
            events.append(
                {
                    "type": "agent_activity",
                    "phase": "review",
                    "label": " · ".join(summary_parts),
                    "verdict": verdict,
                }
            )

    if update.get("error") and merged.get("phase") == "reviewing":
        events.append({"type": "debug", "message": f"Error: {update['error']}"})

    # Every terminal path routes through the finalizer, so the terminal `done`
    # event is emitted only for the finalizer's update. Other nodes may set
    # phase="done" as a routing signal (e.g. reviewer APPROVE), but emitting a
    # `done` for those too would surface duplicate/early terminal events.
    emit_done = node_name is None or node_name == "finalizer"
    if emit_done and merged.get("final_answer") and merged.get("phase") == "done":
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
