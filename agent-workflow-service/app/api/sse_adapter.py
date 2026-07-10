from __future__ import annotations

import json
from typing import Any

from app.agent_workflow.telemetry import trace_event_messages


_ACTIVITY_FIELDS = (
    "phase",
    "tool",
    "label",
    "input_preview",
    "result_preview",
    "error",
    "status",
    "goal",
    "steps",
    "issues",
    "required_changes",
    "missing_evidence",
    "verdict",
    "query",
    "tool_count",
    "tools",
    "fact_count",
    "handoff",
    "answer_chars",
    "revision_cycles",
    "truncated_source_count",
    "preview",
    "artifact_count",
    "explore_cycles",
    "stop_condition",
    "missing",
    "slot_count",
    "updated_slots",
    "cleared_slots",
)


def engine_event_to_sse(event: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    event_type = event.get("type")
    if event_type == "plan":
        return "plan", {
            "goal": event.get("goal", ""),
            "steps": event.get("steps") or [],
            "message": event.get("message", "Plan created"),
        }
    if event_type == "status":
        return "status", {"message": event.get("message", "")}
    if event_type == "debug":
        return "debug", {"message": event.get("message", "")}
    if event_type == "review":
        return "review", {
            "verdict": event.get("verdict"),
            "issues": event.get("issues") or [],
            "missing_evidence": event.get("missing_evidence") or [],
            "required_changes": event.get("required_changes") or [],
            "artifact_count": event.get("artifact_count"),
            "tool_call_count": event.get("tool_call_count"),
            "draft_answer_preview": event.get("draft_answer_preview", ""),
        }
    if event_type == "delta":
        return "delta", {"content": event.get("content", "")}
    if event_type == "agent_activity":
        return "agent_activity", {
            k: event[k]
            for k in _ACTIVITY_FIELDS
            if k in event
        }
    if event_type == "pending_approval":
        return "approval_required", {
            "tool": event.get("tool"),
            "arguments_preview": event.get("arguments_preview"),
            "thread_id": event.get("thread_id"),
        }
    if event_type == "done":
        return "done", {
            "answer": event.get("answer"),
            "review": event.get("review"),
            "artifact_count": event.get("artifact_count"),
            "tool_call_count": event.get("tool_call_count"),
            "has_error": bool(event.get("error")),
            "error": event.get("error"),
            "pending_approval": event.get("pending_approval"),
            "thread_id": event.get("thread_id"),
            "debug_trace": trace_event_messages(event.get("debug_trace") or []),
        }
    return None


def sse_encode(event_name: str, payload: dict[str, Any]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"
