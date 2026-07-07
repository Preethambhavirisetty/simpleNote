from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from app.agent_workflow.util.tokens import count_tokens


def debug_trace_enabled() -> bool:
    """Return whether per-turn debug tracing is enabled by environment flag."""
    value = os.getenv("AGENT_WORKFLOW_DEBUG_TRACE", "").strip().lower()
    return value in {"1", "true", "yes", "y", "on", "debug"}


def _message_token_estimate(messages: Sequence[dict[str, Any]]) -> int:
    # This is only a fallback. The OpenAI-compatible provider records exact
    # prompt/completion/total tokens when the upstream response includes usage.
    """Estimate prompt tokens from message role and content text."""
    total = 0
    for message in messages:
        total += count_tokens(str(message.get("role", "")))
        total += count_tokens(str(message.get("content", "")))
        total += 4
    return total


def _one_line(text: str, *, limit: int = 500) -> str:
    """Collapse text to one display-safe log line."""
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."


def _preview(value: Any, *, limit: int = 180) -> str:
    """Create a compact one-line preview for values in debug logs."""
    if isinstance(value, (dict, list)):
        return _one_line(json.dumps(value, default=str), limit=limit)
    return _one_line(str(value or ""), limit=limit)


@dataclass
class DebugTrace:
    """Collects one-line debug logs and LLM token usage for a workflow turn."""
    thread_id: str
    user_query: str
    started_at: float = field(default_factory=time.time)
    _calls: list[dict[str, Any]] = field(default_factory=list)
    _events: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, message: str, **extra: Any) -> None:
        """Append one one-line message to the current trace."""
        entry = {"step": "debug_trace.log", "message": _one_line(message)}
        if extra:
            entry.update(extra)
        with self._lock:
            self._events.append(entry)

    def start_llm_call(
        self,
        *,
        node: str,
        label: str,
        messages: Sequence[dict[str, Any]],
        max_tokens: int,
    ) -> dict[str, Any]:
        """Register a labeled LLM call and log its starting context size."""
        with self._lock:
            sequence = len(self._calls) + 1
            call = {
                "sequence": sequence,
                "node": node,
                "label": label,
                "max_tokens": max_tokens,
                "message_count": len(messages),
                "prompt_tokens_estimated": _message_token_estimate(messages),
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "usage_source": "pending",
                "started_at": time.time(),
            }
            self._calls.append(call)
            self._events.append(
                {
                    "step": "debug_trace.log",
                    "message": _one_line(
                        f"{node} node started {label}; context tokens: {call['prompt_tokens_estimated']}; "
                        f"messages: {len(messages)}; max output tokens: {max_tokens}"
                    ),
                    "trace": dict(call),
                }
            )
            return call

    def finish_llm_call(self, call: dict[str, Any], *, error: str | None = None) -> None:
        """Finalize one traced LLM call with usage, latency, and errors."""
        with self._lock:
            call["latency_ms"] = int((time.time() - float(call.get("started_at") or time.time())) * 1000)
            if error:
                call["error"] = error[:300]
            if not call.get("total_tokens"):
                call["usage_source"] = "estimate"
                call["prompt_tokens"] = int(call.get("prompt_tokens_estimated") or 0)
                call["completion_tokens"] = 0
                call["total_tokens"] = int(call.get("prompt_tokens") or 0)
            line = (
                f"{call['node']} node finished {call['label']}; prompt tokens: {call['prompt_tokens']}; "
                f"completion tokens: {call['completion_tokens']}; total tokens: {call['total_tokens']}; "
                f"source: {call['usage_source']}; latency ms: {call['latency_ms']}"
            )
            if error:
                line = f"{line}; error: {error[:120]}"
            self._events.append({"step": "debug_trace.log", "message": _one_line(line), "trace": dict(call)})

    def record_usage(self, usage: dict[str, Any], call: dict[str, Any] | None) -> None:
        """Record usage into workflow state or telemetry."""
        if call is None:
            return
        with self._lock:
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = usage.get(key)
                if isinstance(value, int):
                    call[key] = int(call.get(key) or 0) + value
            call["usage_source"] = "provider"

    def final_events(self) -> list[dict[str, Any]]:
        """Return all trace events plus a final token/latency summary."""
        with self._lock:
            total = {
                "prompt_tokens": sum(int(call.get("prompt_tokens") or 0) for call in self._calls),
                "completion_tokens": sum(int(call.get("completion_tokens") or 0) for call in self._calls),
                "total_tokens": sum(int(call.get("total_tokens") or 0) for call in self._calls),
                "llm_calls": len(self._calls),
                "elapsed_ms": int((time.time() - self.started_at) * 1000),
            }
            summary = (
                f"turn finished; thread: {self.thread_id}; llm calls: {total['llm_calls']}; "
                f"prompt tokens: {total['prompt_tokens']}; completion tokens: {total['completion_tokens']}; "
                f"total tokens: {total['total_tokens']}; elapsed ms: {total['elapsed_ms']}"
            )
            return list(self._events) + [
                {"step": "debug_trace.summary", "message": _one_line(summary), "usage": total}
            ]


_TRACE: ContextVar[DebugTrace | None] = ContextVar("agent_workflow_debug_trace", default=None)
_LLM_CALL: ContextVar[dict[str, Any] | None] = ContextVar("agent_workflow_debug_llm_call", default=None)


@contextmanager
def llm_call(
    *,
    node: str,
    label: str,
    messages: Sequence[dict[str, Any]],
    max_tokens: int,
) -> Iterator[None]:
    """Record one labeled LLM call inside the active debug trace."""
    trace = _TRACE.get()
    if trace is None:
        yield
        return
    call = trace.start_llm_call(node=node, label=label, messages=messages, max_tokens=max_tokens)
    token = _LLM_CALL.set(call)
    try:
        yield
    except Exception as exc:
        trace.finish_llm_call(call, error=str(exc))
        raise
    else:
        trace.finish_llm_call(call)
    finally:
        _LLM_CALL.reset(token)


def record_llm_usage(usage: Any) -> None:
    """Attach provider-reported token usage to the active traced LLM call."""
    trace = _TRACE.get()
    if trace is None or not isinstance(usage, dict):
        return
    trace.record_usage(usage, _LLM_CALL.get())


def begin_turn_trace(thread_id: str, user_query: str) -> DebugTrace | None:
    """Start collecting one-line debug logs for a workflow turn."""
    if not debug_trace_enabled():
        return None
    trace = DebugTrace(thread_id=thread_id, user_query=user_query)
    token = _TRACE.set(trace)
    setattr(trace, "_context_token", token)
    trace.add(f"user question: {user_query}; question tokens: {count_tokens(user_query)}; thread: {thread_id}")
    return trace


def finish_turn_trace() -> list[dict[str, Any]]:
    """Finish the active debug trace and return its accumulated events."""
    trace = _TRACE.get()
    if trace is None:
        return []
    events = trace.final_events()
    token = getattr(trace, "_context_token", None)
    if token is not None:
        _TRACE.reset(token)
    else:
        _TRACE.set(None)
    return events


def trace_event_messages(events: list[Any]) -> list[str]:
    """Convert debug trace event objects into display-ready one-line strings."""
    lines: list[str] = []
    for event in events:
        if isinstance(event, dict):
            if not str(event.get("step") or "").startswith("debug_trace"):
                continue
            message = str(event.get("message") or "").strip()
        else:
            message = str(event or "").strip()
        if message:
            lines.append(message)
    return lines


def record_workflow_update(update: dict[str, Any], previous_state: dict[str, Any]) -> None:
    """Translate graph node updates into human-readable debug trace lines."""
    trace = _TRACE.get()
    if trace is None:
        return

    if update.get("plan"):
        plan = update.get("plan") or {}
        steps = plan.get("steps") or []
        trace.add(f"planner created plan; goal: {_preview(plan.get('goal'))}; steps: {len(steps)}")
        for idx, step in enumerate(steps, start=1):
            title = _preview(step.get("title"))
            action = _preview(step.get("action"), limit=240)
            hint = _preview(step.get("tool_hint"))
            suffix = f"; tool hint: {hint}" if hint else ""
            trace.add(f"planner step {idx}: {title}; action: {action}{suffix}")

    for event in update.get("events") or []:
        step = str(event.get("step") or "")
        if step == "planner.skipped":
            trace.add(f"planner skipped; reason: {_preview(event.get('reason'))}")
        elif step == "planner.timeout":
            trace.add(f"planner timed out; error: {_preview(event.get('error'))}")
        elif step == "executor.action":
            trace.add(
                "executor chose action: "
                f"{_preview(event.get('action'))}; turn: {event.get('executor_turn')}; "
                f"plan step: {int(event.get('step_index', 0)) + 1}; title: {_preview(event.get('step_title'))}"
            )
        elif step == "executor.search_tools":
            tools = event.get("tools") or []
            trace.add(
                "executor searched tools; "
                f"query: {_preview(event.get('query'), limit=220)}; "
                f"cache hit: {bool(event.get('cache_hit'))}; candidates: {event.get('tool_count', len(tools))}; "
                f"tools: {_preview(', '.join(str(tool) for tool in tools), limit=220)}"
            )
        elif step == "executor.call_tool":
            trace.add(
                "executor called tool; "
                f"name: {_preview(event.get('tool'))}; status: {_preview(event.get('status'))}; "
                f"latency ms: {event.get('latency_ms', '')}; score: {event.get('artifact_score', '')}; "
                f"artifact: {_preview(event.get('artifact_id'))}; args: {_preview(event.get('arguments'), limit=220)}; "
                f"error: {_preview(event.get('error'))}"
            )
        elif step == "executor.finish_step":
            trace.add(f"executor finished plan step {int(event.get('step_index', 0)) + 1}")
        elif step == "executor.draft_answer":
            trace.add(f"executor received draft action; handoff: {_preview(event.get('handoff'))}")
        elif step == "executor.completed_steps":
            trace.add(f"executor completed planned steps; handoff: {_preview(event.get('handoff'))}")
        elif step == "executor.iteration_limit":
            trace.add(f"executor hit iteration limit; handoff: {_preview(event.get('handoff'))}")
        elif step == "fact_extractor.completed":
            trace.add(
                "fact extractor completed; "
                f"facts: {event.get('fact_count')}; artifacts: {event.get('artifact_count')}; "
                f"truncated sources: {event.get('truncated_source_count')}"
            )
        elif step == "synthesizer.completed":
            trace.add(
                "synthesizer completed; "
                f"facts: {event.get('fact_count')}; answer chars: {event.get('answer_chars')}"
            )
        elif step == "synthesizer.timeout":
            trace.add(f"synthesizer timed out; error: {_preview(event.get('error'))}")
        elif step == "revision.completed":
            trace.add(
                "revision completed; "
                f"cycles: {event.get('revision_cycles')}; answer chars: {event.get('answer_chars')}"
            )
        elif step == "revision.timeout":
            trace.add(f"revision timed out; error: {_preview(event.get('error'))}")
        elif step == "revision.limit_reached":
            trace.add(f"revision limit reached; cycles: {event.get('revision_cycles')}")
        elif step == "executor.tool_args_invalid":
            trace.add(f"executor rejected tool arguments; tool: {_preview(event.get('tool'))}; error: {_preview(event.get('error'))}")
        elif step in {
            "executor.tool_candidates_available",
            "executor.duplicate_tool_skipped",
            "executor.tool_limit_reached",
            "executor.search_loop_breaker",
            "executor.required_tools_missing",
            "executor.tool_policy_blocked",
            "executor.destructive_denied",
            "executor.destructive_skipped",
            "executor.approval_required",
            "approval.approved",
            "approval.denied",
        }:
            message = event.get("message") or step.replace(".", " ")
            trace.add(f"{message}; details: {_preview(event)}")
        elif step == "reviewer.completed":
            trace.add(
                "reviewer completed; "
                f"verdict: {_preview(event.get('verdict'))}; issues: {len(event.get('issues') or [])}; "
                f"missing evidence: {len(event.get('missing_evidence') or [])}; "
                f"required changes: {len(event.get('required_changes') or [])}; "
                f"facts: {event.get('fact_count')}; artifacts: {event.get('artifact_count')}; "
                f"tool calls: {event.get('tool_call_count')}"
            )
        elif step == "reviewer.skipped":
            trace.add(f"reviewer skipped; reason: {_preview(event.get('reason'))}")
        elif step == "reviewer.timeout":
            trace.add(f"reviewer timed out; error: {_preview(event.get('error'))}")
        elif step == "reviewer.limit_reached":
            trace.add(f"reviewer limit reached; cycles: {event.get('review_cycles')}")
        elif step.startswith("finalizer."):
            trace.add(f"{step.replace('.', ' ')}; details: {_preview(event)}")

    if update.get("error"):
        trace.add(
            f"workflow error set; phase: {_preview(update.get('phase') or previous_state.get('phase'))}; "
            f"error: {_preview(update.get('error'))}"
        )
