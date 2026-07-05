from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import GraphRecursionError
from langgraph.types import Command

from app.agent_workflow.cache import get_or_create_graph, get_or_create_provider
from app.agent_workflow.checkpointing import delete_thread
from app.agent_workflow.config import AgentConfig, load_agent_config, merge_agent_config, parse_agent_config
from app.agent_workflow.graph import build_graph
from app.agent_workflow.providers import OpenAiChatCompletionsProvider, create_tool_provider
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.providers.tools import ToolProvider
from app.agent_workflow.runtime_schema import RunRequestModel
from app.agent_workflow.state import AgentState
from app.agent_workflow.streaming import HostCallbacks, RunRequest, RunResult, map_graph_update


_TOOL_INTENT_RE = re.compile(
    r"\b(note|notes|document|documents|doc|docs|folder|folders|search|find|locate|summari[sz]e|"
    r"list|retrieve|cite|citation|source|page|chunk|upload|delete|update|create|edit|workflow|"
    r"database|record|file|files|mcp|tool)\b",
    re.IGNORECASE,
)
_COMPLEX_INTENT_RE = re.compile(
    r"\b(compare|analy[sz]e|investigate|research|plan|multi[- ]?step|all|every|across|audit|"
    r"trace|debug|integrate|deploy|production|architecture)\b",
    re.IGNORECASE,
)
_SIMPLE_MATH_RE = re.compile(r"^[\s\d+\-*/().,%=^xX]+$")
_ARITHMETIC_EXPR_RE = re.compile(r"\d\s*[+\-*/xX]\s*\d")
_GREETING_RE = re.compile(r"^(hi|hello|hey|thanks|thank you|ok|okay|yes|no)[!.\s]*$", re.IGNORECASE)


def _merge_state(state: AgentState, update: dict[str, Any], *, max_events: int = 80) -> AgentState:
    merged = {**state, **update}
    if "events" in update:
        events = list(state.get("events") or []) + list(update["events"])
        merged["events"] = events[-max_events:] if max_events > 0 else []
    return merged


@dataclass
class AgentEngine:
    """Compile-once agent runtime.

    The graph is compiled a single time with a checkpointer, so every run is
    durable per thread_id: a destructive tool call with no synchronous approver
    pauses at the approval node's interrupt, and `resume(thread_id, approved=…)`
    continues from the checkpoint. The default MemorySaver is per-process;
    inject a durable checkpointer (e.g. Postgres) for multi-worker deployments.
    """

    config: AgentConfig
    llm: LlmProvider
    tools: ToolProvider
    callbacks: HostCallbacks
    checkpointer: Any = None
    graph: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        signature = self.config.signature()
        cache_signature = signature if self.checkpointer is None else f"{signature}:checkpointer:{id(self.checkpointer)}"

        def _build_cached() -> tuple[Any, Any]:
            checkpointer = self.checkpointer or MemorySaver()
            graph = build_graph(
                self.config,
                self.llm,
                self.tools,
                callbacks=self._callback_map(),
                checkpointer=checkpointer,
            )
            return graph, checkpointer

        self.graph, self.checkpointer = get_or_create_graph(cache_signature, _build_cached)

    @classmethod
    def from_config(
        cls,
        path: str | Path,
        *,
        callbacks: HostCallbacks | None = None,
        checkpointer: Any = None,
        llm: LlmProvider | None = None,
        tools: ToolProvider | None = None,
    ) -> "AgentEngine":
        config = load_agent_config(path)
        signature = config.signature()
        llm_provider = llm or get_or_create_provider(
            signature,
            "llm",
            lambda: OpenAiChatCompletionsProvider.from_agent_config(config),
        )
        tool_provider = tools or get_or_create_provider(
            signature,
            "tools",
            lambda: create_tool_provider(config.mcp),
        )
        return cls(
            config=config,
            llm=llm_provider,
            tools=tool_provider,
            callbacks=callbacks or HostCallbacks(),
            checkpointer=checkpointer,
        )

    @classmethod
    def from_dict(
        cls,
        raw: dict[str, Any],
        *,
        base_dir: str | Path | None = None,
        callbacks: HostCallbacks | None = None,
        checkpointer: Any = None,
        llm: LlmProvider | None = None,
        tools: ToolProvider | None = None,
    ) -> "AgentEngine":
        config = parse_agent_config(raw, base_dir=Path(base_dir).resolve() if base_dir else None)
        signature = config.signature()
        llm_provider = llm or get_or_create_provider(
            signature,
            "llm",
            lambda: OpenAiChatCompletionsProvider.from_agent_config(config),
        )
        tool_provider = tools or get_or_create_provider(
            signature,
            "tools",
            lambda: create_tool_provider(config.mcp),
        )
        return cls(
            config=config,
            llm=llm_provider,
            tools=tool_provider,
            callbacks=callbacks or HostCallbacks(),
            checkpointer=checkpointer,
        )

    @classmethod
    def from_runtime_config(
        cls,
        base: str | Path | dict[str, Any],
        runtime_overrides: dict[str, Any] | None = None,
        *,
        callbacks: HostCallbacks | None = None,
        checkpointer: Any = None,
        llm: LlmProvider | None = None,
        tools: ToolProvider | None = None,
    ) -> "AgentEngine":
        if isinstance(base, (str, Path)):
            config = load_agent_config(base)
        else:
            config = parse_agent_config(base)
        if runtime_overrides:
            config = merge_agent_config(config, runtime_overrides)
        signature = config.signature()
        llm_provider = llm or get_or_create_provider(
            signature,
            "llm",
            lambda: OpenAiChatCompletionsProvider.from_agent_config(config),
        )
        tool_provider = tools or get_or_create_provider(
            signature,
            "tools",
            lambda: create_tool_provider(config.mcp),
        )
        return cls(
            config=config,
            llm=llm_provider,
            tools=tool_provider,
            callbacks=callbacks or HostCallbacks(),
            checkpointer=checkpointer,
        )

    @staticmethod
    def _validate_request(request: RunRequest) -> RunRequest:
        model = RunRequestModel.model_validate(
            {
                "query": request.query,
                "session_id": request.session_id,
                "history": request.history,
                "runtime_context": request.runtime_context,
            }
        )
        return RunRequest(
            query=model.query,
            session_id=model.session_id,
            history=[item.model_dump(mode="json") for item in model.history],
            runtime_context=dict(model.runtime_context),
        )

    def _can_fast_path(self, request: RunRequest) -> tuple[bool, str]:
        if not self.config.policy.enable_fast_path:
            return False, "disabled"
        query = request.query.strip()
        if not query:
            return False, "empty_query"
        runtime = request.runtime_context or {}
        if runtime.get("force_agent") or runtime.get("require_tools"):
            return False, "forced_agent"
        if request.history and len(query.split()) > 8:
            return False, "conversation_context"
        if len(query) > 180 or len(query.split()) > 24:
            return False, "too_long"
        if _TOOL_INTENT_RE.search(query) or _COMPLEX_INTENT_RE.search(query):
            return False, "tool_or_complex_intent"
        if _GREETING_RE.match(query) or _SIMPLE_MATH_RE.match(query):
            return True, "simple_heuristic"
        if _ARITHMETIC_EXPR_RE.search(query) and len(query.split()) <= 8:
            return True, "simple_arithmetic"
        if query.endswith("?") and len(query.split()) <= 10 and runtime.get("allow_ungrounded"):
            return True, "explicit_ungrounded_short_question"
        return False, "not_simple"

    def _direct_answer_messages(self, request: RunRequest) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "Answer the user's simple request directly and concisely. "
                    "Do not claim to have searched notes, documents, tools, or external systems."
                ),
            }
        ]
        for item in request.history[-4:]:
            role = str(item.get("role") or "user")
            if role not in {"system", "user", "assistant"}:
                role = "user"
            messages.append({"role": role, "content": str(item.get("content") or "")[:1000]})
        messages.append({"role": "user", "content": request.query.strip()})
        return messages

    def _fast_path_result(self, request: RunRequest, thread_id: str, reason: str) -> RunResult:
        answer = self.llm.complete(self._direct_answer_messages(request), max_tokens=512).strip()
        return RunResult(
            answer=answer,
            review={"verdict": "SKIPPED", "reason": reason},
            artifacts=[],
            tool_calls=[],
            events=[{"step": "router.fast_path", "reason": reason}],
            thread_id=thread_id,
        )

    def _emit_fast_path_event(self, event: dict[str, Any]) -> dict[str, Any]:
        if self.callbacks.on_event:
            self.callbacks.on_event(event)
        return event

    def _stream_fast_path(self, request: RunRequest, thread_id: str, reason: str) -> Iterator[dict[str, Any]]:
        yield self._emit_fast_path_event(
            {
                "type": "debug",
                "message": f"Fast path selected: {reason}",
                "thread_id": thread_id,
            }
        )
        parts: list[str] = []
        try:
            for token in self.llm.stream(self._direct_answer_messages(request), max_tokens=512):
                if not token:
                    continue
                parts.append(token)
                yield self._emit_fast_path_event({"type": "delta", "content": token, "thread_id": thread_id})
        except Exception as exc:
            if not parts:
                answer = self.llm.complete(self._direct_answer_messages(request), max_tokens=512).strip()
                parts.append(answer)
                yield self._emit_fast_path_event({"type": "delta", "content": answer, "thread_id": thread_id})
            yield self._emit_fast_path_event(
                {"type": "debug", "message": f"Fast-path stream fell back to complete: {exc}", "thread_id": thread_id}
            )
        yield self._emit_fast_path_event(
            {
                "type": "done",
                "answer": "".join(parts),
                "review": {"verdict": "SKIPPED", "reason": reason},
                "artifact_count": 0,
                "tool_call_count": 0,
                "error": None,
                "thread_id": thread_id,
            }
        )

    def _initial_state(self, request: RunRequest) -> AgentState:
        plan = {}
        phase = "planning"
        planner_enabled = self.config.policy.enable_planner and self.config.policy.planner.enabled
        if not planner_enabled:
            plan = {
                "goal": request.query.strip(),
                "steps": [
                    {
                        "title": "Execute request",
                        "action": request.query.strip(),
                        "tool_hint": "auto",
                    }
                ],
            }
            phase = "executing"

        return AgentState(
            messages=list(request.history),
            user_query=request.query.strip(),
            session_id=request.session_id,
            runtime_context=dict(request.runtime_context),
            plan=plan,
            current_step_index=0,
            candidate_tools=[],
            tool_discovery_cache={},
            artifacts=[],
            tool_calls=[],
            draft_answer="",
            review={},
            review_feedback="",
            iteration={"executor_turns": 0, "review_cycles": 0, "tool_calls": 0},
            events=[],
            phase=phase,
            final_answer="",
            error=None,
            pending_destructive=None,
        )

    def _callback_map(self) -> dict[str, Any]:
        return {
            "on_tool_search": self.callbacks.on_tool_search,
            "on_tool_call": self.callbacks.on_tool_call,
            "on_artifact": self.callbacks.on_artifact,
            "on_destructive_action": self.callbacks.on_destructive_action,
        }

    def _new_thread_id(self, session_id: str) -> str:
        # Unique per run: reusing a conversation-scoped id verbatim would collide
        # with the previous turn's checkpoint (including a paused interrupt).
        return f"{session_id or 'run'}-{uuid.uuid4().hex[:12]}"

    def _thread_config(self, thread_id: str) -> dict[str, Any]:
        review_cycles = max(0, self.config.policy.reviewer.max_cycles)
        review_passes = max(1, review_cycles + 1)
        replan_passes = max(1, review_cycles + 1)
        executor_budget = self.config.policy.max_executor_iterations * review_passes * replan_passes
        return {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": max(25, executor_budget + 8),
        }

    @staticmethod
    def _awaiting_answer(pending: dict[str, Any]) -> str:
        tool = pending.get("tool") or "a destructive tool"
        return (
            f"This request needs an action that requires approval: {tool}. "
            "The run is paused until the action is approved or denied."
        )

    def _recursion_error_result(self, state: AgentState, exc: GraphRecursionError, thread_id: str) -> RunResult:
        answer = str(state.get("final_answer") or state.get("draft_answer") or "")
        if not answer and state.get("artifacts"):
            from app.agent_workflow.nodes.executor import _fallback_answer

            answer = _fallback_answer(state)
        return RunResult(
            answer=answer,
            review=dict(state.get("review") or {}),
            artifacts=list(state.get("artifacts") or []),
            tool_calls=list(state.get("tool_calls") or []),
            events=list(state.get("events") or []) + [{"step": "graph.recursion_limit", "error": str(exc)}],
            error="Graph recursion limit reached; returning best-effort answer.",
            thread_id=thread_id,
        )

    # ── update pump (shared by run/stream/resume) ──────────────────────────────

    def _pending_events_from_interrupt(self, raw_interrupt: Any, thread_id: str) -> Iterator[dict[str, Any]]:
        interrupts = raw_interrupt if isinstance(raw_interrupt, (list, tuple)) else [raw_interrupt]
        for intr in interrupts:
            payload = getattr(intr, "value", None)
            event = {
                "type": "pending_approval",
                "thread_id": thread_id,
                **(payload if isinstance(payload, dict) else {"value": payload}),
            }
            if self.callbacks.on_event:
                self.callbacks.on_event(event)
            yield event

    def _pump(
        self,
        stream: Iterator[dict[str, Any]],
        holder: dict[str, Any],
        thread_id: str,
        *,
        emit_done: bool = True,
    ) -> Iterator[dict[str, Any]]:
        """Translate raw graph updates into host events while folding state."""
        for step in stream:
            for node_name, update in step.items():
                if node_name == "__interrupt__":
                    yield from self._pending_events_from_interrupt(update, thread_id)
                    continue
                if isinstance(update, dict) and "__interrupt__" in update:
                    yield from self._pending_events_from_interrupt(update["__interrupt__"], thread_id)
                    continue
                if not isinstance(update, dict):
                    continue
                if update.get("plan") and self.callbacks.on_plan:
                    self.callbacks.on_plan(dict(update["plan"]))
                if update.get("review") and self.callbacks.on_review:
                    self.callbacks.on_review(dict(update["review"]))

                for event in map_graph_update(update, holder["state"]):
                    if event.get("type") == "done":
                        if not emit_done:
                            continue
                        event["thread_id"] = thread_id
                    if self.callbacks.on_event:
                        self.callbacks.on_event(event)
                    yield event

                holder["state"] = _merge_state(
                    holder["state"],
                    update,
                    max_events=self.config.policy.max_retained_events,
                )

    @staticmethod
    def _pending_approval_event(state: AgentState, thread_id: str) -> dict[str, Any] | None:
        pending = state.get("pending_destructive")
        if state.get("phase") != "awaiting_approval" or not pending:
            return None
        event = {"type": "pending_approval", "thread_id": thread_id}
        event.update(dict(pending))
        return event

    @staticmethod
    def _error_result(thread_id: str, error: str) -> RunResult:
        return RunResult(
            answer="",
            review={},
            artifacts=[],
            tool_calls=[],
            events=[],
            error=error,
            thread_id=thread_id,
        )

    def _final_event(self, state: AgentState, thread_id: str) -> dict[str, Any] | None:
        """Build the single terminal event emitted by stream/resume_stream."""
        pending = state.get("pending_destructive")
        if state.get("phase") == "awaiting_approval" and pending:
            return {
                "type": "done",
                "answer": self._awaiting_answer(pending),
                "review": state.get("review"),
                "artifact_count": len(state.get("artifacts") or []),
                "tool_call_count": len(state.get("tool_calls") or []),
                "error": None,
                "pending_approval": dict(pending),
                "thread_id": thread_id,
            }
        return {
            "type": "done",
            "answer": state.get("final_answer") or state.get("draft_answer") or "",
            "review": state.get("review"),
            "artifact_count": len(state.get("artifacts") or []),
            "tool_call_count": len(state.get("tool_calls") or []),
            "error": state.get("error"),
            "thread_id": thread_id,
        }

    def _terminal_answer_messages(self, state: AgentState) -> list[dict[str, str]]:
        approved = str(state.get("final_answer") or state.get("draft_answer") or "").strip()
        return [
            {
                "role": "system",
                "content": (
                    "You are the final answer renderer for an agent workflow. "
                    "Write only the final user-facing answer. Preserve the approved meaning, "
                    "do not add unsupported claims, and do not mention the review process."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"User request:\n{state.get('user_query', '')}\n\n"
                    f"Approved answer or best available draft:\n{approved}\n\n"
                    "Return only the answer text."
                ),
            },
        ]

    def _stream_terminal_answer(self, state: AgentState, thread_id: str) -> Iterator[dict[str, Any]]:
        if state.get("phase") != "done" or state.get("pending_destructive"):
            return
        existing = str(state.get("final_answer") or state.get("draft_answer") or "").strip()
        if not existing:
            return

        parts: list[str] = []
        try:
            for token in self.llm.stream(self._terminal_answer_messages(state), max_tokens=2000):
                if not token:
                    continue
                parts.append(token)
                event = {"type": "delta", "content": token, "thread_id": thread_id}
                if self.callbacks.on_event:
                    self.callbacks.on_event(event)
                yield event
        except Exception as exc:  # noqa: BLE001
            if not parts:
                parts.append(existing)
                event = {"type": "delta", "content": existing, "thread_id": thread_id}
                if self.callbacks.on_event:
                    self.callbacks.on_event(event)
                yield event
            debug = {"type": "debug", "message": f"Answer stream failed; used fallback text: {exc}"}
            if self.callbacks.on_event:
                self.callbacks.on_event(debug)
            yield debug


    def _cleanup_thread_if_terminal(self, state: AgentState, thread_id: str) -> None:
        if state.get("phase") == "awaiting_approval" or state.get("pending_destructive"):
            return
        delete_thread(self.checkpointer, thread_id)

    def _result_from_state(self, state: AgentState, thread_id: str) -> RunResult:
        pending = state.get("pending_destructive")
        awaiting = state.get("phase") == "awaiting_approval" and bool(pending)
        answer = str(state.get("final_answer") or state.get("draft_answer") or "")
        if awaiting and not answer:
            answer = self._awaiting_answer(pending)
        return RunResult(
            answer=answer,
            review=dict(state.get("review") or {}),
            artifacts=list(state.get("artifacts") or []),
            tool_calls=list(state.get("tool_calls") or []),
            events=list(state.get("events") or []),
            error=state.get("error"),
            pending_approval=dict(pending) if awaiting else None,
            thread_id=thread_id,
        )

    def _llm_usage_snapshot(self) -> dict[str, int]:
        usage = getattr(self.llm, "usage_totals", None)
        if not callable(usage):
            return {}
        try:
            return {str(k): int(v) for k, v in usage().items()}
        except Exception:  # noqa: BLE001
            return {}

    @staticmethod
    def _llm_usage_delta(start: dict[str, int], end: dict[str, int]) -> dict[str, int]:
        keys = set(start) | set(end)
        return {key: max(0, int(end.get(key, 0)) - int(start.get(key, 0))) for key in keys}

    def _attach_usage_event(self, result: RunResult, usage_start: dict[str, int]) -> RunResult:
        usage = self._llm_usage_delta(usage_start, self._llm_usage_snapshot())
        if usage:
            result.events.append({"step": "telemetry.llm_usage", "usage": usage})
        return result

    # ── public API ─────────────────────────────────────────────────────────────

    def run(self, request: RunRequest) -> RunResult:
        request = self._validate_request(request)
        thread_id = self._new_thread_id(request.session_id)
        fast_path, reason = self._can_fast_path(request)
        if fast_path:
            return self._fast_path_result(request, thread_id, reason)
        holder = {"state": self._initial_state(request)}
        usage_start = self._llm_usage_snapshot()
        try:
            stream = self.graph.stream(
                holder["state"], stream_mode="updates", config=self._thread_config(thread_id)
            )
            for _event in self._pump(stream, holder, thread_id):
                pass
        except GraphRecursionError as exc:
            result = self._recursion_error_result(holder["state"], exc, thread_id)
            self._attach_usage_event(result, usage_start)
            self._cleanup_thread_if_terminal(holder["state"], thread_id)
            return result
        result = self._result_from_state(holder["state"], thread_id)
        self._attach_usage_event(result, usage_start)
        self._cleanup_thread_if_terminal(holder["state"], thread_id)
        return result

    def stream(self, request: RunRequest) -> Iterator[dict[str, Any]]:
        request = self._validate_request(request)
        thread_id = self._new_thread_id(request.session_id)
        fast_path, reason = self._can_fast_path(request)
        if fast_path:
            yield from self._stream_fast_path(request, thread_id, reason)
            return

        holder = {"state": self._initial_state(request)}
        usage_start = self._llm_usage_snapshot()
        yielded_pending_approval = False

        yield {"type": "status", "message": "Planning...", "thread_id": thread_id}

        stream = None
        try:
            stream = self.graph.stream(
                holder["state"], stream_mode="updates", config=self._thread_config(thread_id)
            )
            for event in self._pump(stream, holder, thread_id, emit_done=False):
                if event.get("type") == "pending_approval":
                    yielded_pending_approval = True
                yield event
        except GeneratorExit:
            if stream is not None and hasattr(stream, "close"):
                stream.close()
            if self.callbacks.on_event:
                self.callbacks.on_event({"type": "debug", "message": "Run cancelled by client disconnect", "thread_id": thread_id})
            raise
        except GraphRecursionError as exc:
            result = self._recursion_error_result(holder["state"], exc, thread_id)
            yield self._done_event_from_result(result)
            return

        pending_event = self._pending_approval_event(holder["state"], thread_id)
        if pending_event is not None and not yielded_pending_approval:
            if self.callbacks.on_event:
                self.callbacks.on_event(pending_event)
            yield pending_event

        if pending_event is None:
            answer = str(holder["state"].get("final_answer") or holder["state"].get("draft_answer") or "")
            if answer:
                event = {"type": "delta", "content": answer, "thread_id": thread_id}
                if self.callbacks.on_event:
                    self.callbacks.on_event(event)
                yield event

        final = self._final_event(holder["state"], thread_id)
        if final is not None:
            usage = self._llm_usage_delta(usage_start, self._llm_usage_snapshot())
            if usage:
                final["usage"] = usage
            if self.callbacks.on_event:
                self.callbacks.on_event(final)
            yield final
        self._cleanup_thread_if_terminal(holder["state"], thread_id)

    def resume(self, thread_id: str, *, approved: bool) -> RunResult:
        last_event: dict[str, Any] | None = None
        for event in self.resume_stream(thread_id, approved=approved, cleanup_terminal=False):
            last_event = event
        if last_event and last_event.get("error"):
            return self._error_result(thread_id, str(last_event["error"]))
        state = dict(self.graph.get_state(self._thread_config(thread_id)).values or {})
        result = self._result_from_state(state, thread_id)
        if last_event and last_event.get("type") == "done" and last_event.get("answer"):
            result.answer = str(last_event["answer"])
        self._cleanup_thread_if_terminal(state, thread_id)
        return result

    def resume_stream(self, thread_id: str, *, approved: bool, cleanup_terminal: bool = True) -> Iterator[dict[str, Any]]:
        """Continue a run paused on a destructive-approval interrupt."""
        config = self._thread_config(thread_id)
        try:
            snapshot = self.graph.get_state(config)
            state = dict(snapshot.values or {})
        except Exception:  # noqa: BLE001
            state = {}
        if not state.get("pending_destructive"):
            event = {
                "type": "done",
                "answer": "",
                "error": f"No pending approval for thread {thread_id}.",
                "thread_id": thread_id,
            }
            if self.callbacks.on_event:
                self.callbacks.on_event(event)
            yield event
            return

        holder = {"state": state}
        usage_start = self._llm_usage_snapshot()
        try:
            stream = self.graph.stream(
                Command(resume={"approved": approved}), stream_mode="updates", config=config
            )
            yield from self._pump(stream, holder, thread_id, emit_done=False)
        except GraphRecursionError as exc:
            result = self._recursion_error_result(holder["state"], exc, thread_id)
            yield self._done_event_from_result(result)
            return

        if not holder["state"].get("pending_destructive"):
            answer = str(holder["state"].get("final_answer") or holder["state"].get("draft_answer") or "")
            if answer:
                event = {"type": "delta", "content": answer, "thread_id": thread_id}
                if self.callbacks.on_event:
                    self.callbacks.on_event(event)
                yield event

        final = self._final_event(holder["state"], thread_id)
        if final is not None:
            usage = self._llm_usage_delta(usage_start, self._llm_usage_snapshot())
            if usage:
                final["usage"] = usage
            if self.callbacks.on_event:
                self.callbacks.on_event(final)
            yield final
        if cleanup_terminal:
            self._cleanup_thread_if_terminal(holder["state"], thread_id)

    @staticmethod
    def _done_event_from_result(result: RunResult) -> dict[str, Any]:
        return {
            "type": "done",
            "answer": result.answer,
            "review": result.review,
            "artifact_count": len(result.artifacts),
            "tool_call_count": len(result.tool_calls),
            "error": result.error,
            "thread_id": result.thread_id,
        }
