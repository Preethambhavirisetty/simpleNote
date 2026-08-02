"""
GET  /health
POST /api/agent-workflow/run      JSON, one response
POST /api/agent-workflow/stream   SSE

The path and event names are the ones agent-workflow-service used, because
orchestrator/app/services/chat/streaming.py already speaks them. Keeping the
contract means the swap touches no code in the orchestrator, the backend, or
the frontend. Rename it once this is proven in production.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from config import AGENT_API_KEY
from graph import builder
from graph.context import RunContext
from integrations.domain import DomainUnavailableError, load_catalog
from state.state import Message, RunState

log = logging.getLogger(__name__)

router = APIRouter()

_context: RunContext | None = None


def run_context() -> RunContext:
    """Built on first use, so a slow or late agent-domain does not stop boot."""
    global _context
    if _context is None:
        _context = RunContext(load_catalog())
    return _context


def reset_context() -> None:
    global _context
    _context = None


class RuntimeContextIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    user_id: str
    role: str = "user"
    conversation_id: str | None = None


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    query: str
    session_id: str | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)
    runtime_context: RuntimeContextIn


def _authorise(api_key: str | None) -> None:
    if AGENT_API_KEY and api_key != AGENT_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _history(request: RunRequest) -> list[Message]:
    messages = []
    for item in request.history:
        content = str(item.get("content") or "").strip()
        if content:
            messages.append(Message(role=str(item.get("role") or "user"), content=content))
    return messages


def _start(request: RunRequest) -> RunState:
    return builder.start(
        request.query,
        request.runtime_context.user_id,
        run_context(),
        history=_history(request),
        role=request.runtime_context.role,
    )


def _summary(state: RunState) -> dict[str, Any]:
    tool_calls = [run for run in state.steps if run.call is not None and run.ok]
    payload: dict[str, Any] = {
        "answer": state.answer or "",
        "playbook": state.playbook_id,
        "plan": state.plan_name,
        "reason": state.selection_reason,
        "tool_call_count": len(tool_calls),
        "artifact_count": len(state.structured),
        "records": state.structured,
        "phase": state.phase,
    }
    if state.errors:
        payload["error"] = "; ".join(state.errors)
    if state.pending_approval is not None:
        payload["pending_approval"] = state.pending_approval.model_dump()
    return payload


@router.get("/health")
async def health():
    return {"status": "healthy"}


@router.post("/api/agent-workflow/run")
def run_agent(
    request: RunRequest, x_api_key: str | None = Header(default=None)
) -> dict[str, Any]:
    _authorise(x_api_key)
    try:
        state = _start(request)
    except DomainUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _summary(state)


@router.post("/api/agent-workflow/stream")
def stream_agent(
    request: RunRequest, x_api_key: str | None = Header(default=None)
) -> StreamingResponse:
    _authorise(x_api_key)
    return StreamingResponse(
        _events(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _events(request: RunRequest) -> Iterator[str]:
    """Emit progress, then one terminal `done`.

    Steps are reported as they are discovered rather than as "step 3 of 5":
    a plan that later becomes conditional or looped must not break this
    contract, so nothing here promises a fixed number of steps.
    """
    try:
        state = _start(request)
    except DomainUnavailableError as exc:
        log.warning("domain unavailable", exc_info=True)
        yield _sse("error", {"message": str(exc)})
        yield _sse("done", {"answer": "", "error": str(exc)})
        return
    except Exception as exc:  # a failed run must still close the stream
        log.exception("run failed")
        yield _sse("error", {"message": str(exc)})
        yield _sse("done", {"answer": "", "error": str(exc)})
        return

    yield _sse(
        "status",
        {"phase": "routed", "playbook": state.playbook_id, "plan": state.plan_name},
    )

    for run in state.steps:
        yield _sse(
            "agent_activity",
            {
                "tool": run.call.tool if run.call else run.step,
                "step": run.step,
                "operation": run.operation,
                "phase": "completed" if run.ok else ("paused" if run.paused else "failed"),
            },
        )

    if state.pending_approval is not None:
        yield _sse(
            "approval_required",
            {
                "tool": state.pending_approval.operation,
                **state.pending_approval.model_dump(),
            },
        )
        return

    if state.answer:
        yield _sse("delta", {"content": state.answer})

    yield _sse("done", _summary(state))
