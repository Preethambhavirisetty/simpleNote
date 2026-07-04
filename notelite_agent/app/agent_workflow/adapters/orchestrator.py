from __future__ import annotations

import json
from typing import Any


def engine_event_to_sse(event: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Map AgentEngine events to orchestrator chat SSE event names."""
    event_type = event.get("type")
    if event_type == "status":
        return "status", {"message": event.get("message", "")}
    if event_type == "delta":
        return "delta", {"content": event.get("content", "")}
    if event_type == "agent_activity":
        return "agent_activity", {
            k: event[k]
            for k in ("phase", "tool", "label", "input_preview", "result_preview")
            if k in event
        }
    if event_type == "done":
        return "done", {
            "answer": event.get("answer"),
            "review": event.get("review"),
            "artifact_count": event.get("artifact_count"),
            "tool_call_count": event.get("tool_call_count"),
            "has_error": bool(event.get("error")),
            "error": event.get("error"),
        }
    return None


def sse_encode(event_name: str, payload: dict[str, Any]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"
