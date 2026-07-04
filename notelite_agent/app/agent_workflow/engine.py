from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import GraphRecursionError
from langgraph.types import Command

from app.agent_workflow.config import AgentConfig, load_agent_config
from app.agent_workflow.graph import build_graph
from app.agent_workflow.providers import DefaultLlmProvider, create_tool_provider
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.providers.tools import ToolProvider
from app.agent_workflow.state import AgentState
from app.agent_workflow.streaming import HostCallbacks, RunRequest, RunResult, map_graph_update


def _merge_state(state: AgentState, update: dict[str, Any]) -> AgentState:
    merged = {**state, **update}
    if "events" in update:
        merged["events"] = list(state.get("events") or []) + list(update["events"])
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
        if self.checkpointer is None:
            self.checkpointer = MemorySaver()
        self.graph = build_graph(
            self.config,
            self.llm,
            self.tools,
            callbacks=self._callback_map(),
            checkpointer=self.checkpointer,
        )

    @classmethod
    def from_config(
        cls,
        path: str | Path,
        *,
        callbacks: HostCallbacks | None = None,
        checkpointer: Any = None,
    ) -> "AgentEngine":
        config = load_agent_config(path)
        llm = DefaultLlmProvider(model=config.policy.model)
        tools = create_tool_provider(config.mcp)
        return cls(
            config=config,
            llm=llm,
            tools=tools,
            callbacks=callbacks or HostCallbacks(),
            checkpointer=checkpointer,
        )

    def _initial_state(self, request: RunRequest) -> AgentState:
        return AgentState(
            messages=list(request.history),
            user_query=request.query.strip(),
            session_id=request.session_id,
            runtime_context=dict(request.runtime_context),
            plan={},
            current_step_index=0,
            candidate_tools=[],
            artifacts=[],
            tool_calls=[],
            draft_answer="",
            review={},
            review_feedback="",
            iteration={"executor_turns": 0, "review_cycles": 0, "tool_calls": 0},
            events=[],
            phase="planning",
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
        review_passes = max(1, self.config.policy.max_review_cycles + 1)
        replan_passes = max(1, self.config.policy.max_review_cycles + 1)
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

                holder["state"] = _merge_state(holder["state"], update)

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

        if parts:
            state["final_answer"] = "".join(parts)

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

    # ── public API ─────────────────────────────────────────────────────────────

    def run(self, request: RunRequest) -> RunResult:
        thread_id = self._new_thread_id(request.session_id)
        holder = {"state": self._initial_state(request)}
        try:
            stream = self.graph.stream(
                holder["state"], stream_mode="updates", config=self._thread_config(thread_id)
            )
            for _event in self._pump(stream, holder, thread_id):
                pass
        except GraphRecursionError as exc:
            return self._recursion_error_result(holder["state"], exc, thread_id)
        return self._result_from_state(holder["state"], thread_id)

    def stream(self, request: RunRequest) -> Iterator[dict[str, Any]]:
        thread_id = self._new_thread_id(request.session_id)
        holder = {"state": self._initial_state(request)}
        yielded_pending_approval = False

        yield {"type": "status", "message": "Planning...", "thread_id": thread_id}

        try:
            stream = self.graph.stream(
                holder["state"], stream_mode="updates", config=self._thread_config(thread_id)
            )
            for event in self._pump(stream, holder, thread_id, emit_done=False):
                if event.get("type") == "pending_approval":
                    yielded_pending_approval = True
                yield event
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
            yield from self._stream_terminal_answer(holder["state"], thread_id)

        final = self._final_event(holder["state"], thread_id)
        if final is not None:
            if self.callbacks.on_event:
                self.callbacks.on_event(final)
            yield final

    def resume(self, thread_id: str, *, approved: bool) -> RunResult:
        last_event: dict[str, Any] | None = None
        for event in self.resume_stream(thread_id, approved=approved):
            last_event = event
        if last_event and last_event.get("error"):
            return self._error_result(thread_id, str(last_event["error"]))
        state = dict(self.graph.get_state(self._thread_config(thread_id)).values or {})
        result = self._result_from_state(state, thread_id)
        if last_event and last_event.get("type") == "done" and last_event.get("answer"):
            result.answer = str(last_event["answer"])
        return result

    def resume_stream(self, thread_id: str, *, approved: bool) -> Iterator[dict[str, Any]]:
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
            yield from self._stream_terminal_answer(holder["state"], thread_id)

        final = self._final_event(holder["state"], thread_id)
        if final is not None:
            if self.callbacks.on_event:
                self.callbacks.on_event(final)
            yield final

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
