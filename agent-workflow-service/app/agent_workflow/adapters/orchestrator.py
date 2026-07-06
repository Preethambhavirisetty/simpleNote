from __future__ import annotations

import json
from typing import Any


def engine_event_to_sse(event: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Map AgentEngine events to orchestrator chat SSE event names."""
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
        }
    if event_type == "delta":
        return "delta", {"content": event.get("content", "")}
    if event_type == "agent_activity":
        return "agent_activity", {
            k: event[k]
            for k in ("phase", "tool", "label", "input_preview", "result_preview")
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
        }
    return None


def sse_encode(event_name: str, payload: dict[str, Any]) -> str:
    """Encode one server-sent event frame."""
    return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"
