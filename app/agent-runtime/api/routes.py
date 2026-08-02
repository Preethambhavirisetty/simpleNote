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

import failures
from config import AGENT_API_KEY
from graph import builder
from graph.nodes import classify_state
from graph.context import RunContext
from integrations import observability as obs
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
        raise HTTPException(
            status_code=failures.AUTH_REQUIRED.http_status,
            detail=failures.AUTH_REQUIRED.payload(),
        )


def _history(request: RunRequest) -> list[Message]:
    messages = []
    for item in request.history:
        content = str(item.get("content") or "").strip()
        if content:
            messages.append(Message(role=str(item.get("role") or "user"), content=content))
    return messages


def _start(request: RunRequest) -> RunState:
    """One request, one logged run - the unit the dashboard groups by."""
    with obs.run_logger(
        request.query,
        request.runtime_context.conversation_id or request.session_id,
        user_id=request.runtime_context.user_id,
        role=request.runtime_context.role,
    ):
        state = builder.start(
            request.query,
            request.runtime_context.user_id,
            run_context(),
            history=_history(request),
            role=request.runtime_context.role,
        )
        obs.finish(
            state.answer,
            status="error" if state.phase == "failed" else "ok",
            playbook=state.playbook_id,
            plan=state.plan_name,
            phase=state.phase,
        )
        return state


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
        # `error` stays a plain string for existing consumers; `failure` is the
        # structured form the UI reads.
        detail = "; ".join(state.errors)
        payload["error"] = detail
        payload["failure"] = failures.get(state.failure_code).payload(detail)
    elif state.failure_code:
        # A refusal is not an error - the run succeeded at deciding not to act -
        # but the client still needs the code to render it as a refusal rather
        # than as an ordinary answer.
        payload["failure"] = failures.get(state.failure_code).payload()
    if state.pending_approval is not None:
        payload["pending_approval"] = state.pending_approval.model_dump()
        payload["failure"] = failures.APPROVAL_REQUIRED.payload()
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
        raise HTTPException(
            status_code=failures.DOMAIN_UNAVAILABLE.http_status,
            detail=failures.DOMAIN_UNAVAILABLE.payload(str(exc)),
        ) from exc
    except Exception as exc:
        # Anything unhandled here used to leave as a bare 500 with an empty
        # body, so the caller learned nothing. Classify it like the stream
        # path does; the raw cause stays in the log and in `detail`.
        failure = failures.classify(exc)
        log.exception("run failed", extra={"failure_code": failure.code})
        raise HTTPException(
            status_code=failure.http_status, detail=failure.payload(str(exc))
        ) from exc
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


def _fail(failure: failures.Failure, exc: BaseException) -> Iterator[str]:
    """Terminate a stream with one failure, in the shape every service uses.

    Both events carry it: `error` is what a live client renders, and `done`
    repeats it so a consumer that only reads the terminal event - or replays
    the persisted message later - sees the same code and copy.
    """
    body = failure.payload(str(exc))
    yield _sse("error", body)
    yield _sse("done", {"answer": "", "error": failure.message, "failure": body})


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
        yield from _fail(failures.DOMAIN_UNAVAILABLE, exc)
        return
    except Exception as exc:  # a failed run must still close the stream
        log.exception("run failed")
        yield from _fail(failures.classify(exc), exc)
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
                **failures.APPROVAL_REQUIRED.payload(),
                **state.pending_approval.model_dump(),
            },
        )
        return

    if state.answer:
        yield _sse("delta", {"content": state.answer})

    yield _sse("done", _summary(state))
