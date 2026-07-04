from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langgraph.errors import GraphRecursionError

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
    config: AgentConfig
    llm: LlmProvider
    tools: ToolProvider
    callbacks: HostCallbacks

    @classmethod
    def from_config(cls, path: str | Path, *, callbacks: HostCallbacks | None = None) -> "AgentEngine":
        config = load_agent_config(path)
        llm = DefaultLlmProvider(model=config.policy.model)
        tools = create_tool_provider(config.mcp)
        return cls(config=config, llm=llm, tools=tools, callbacks=callbacks or HostCallbacks())

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
        )

    def _callback_map(self) -> dict[str, Any]:
        return {
            "on_tool_search": self.callbacks.on_tool_search,
            "on_tool_call": self.callbacks.on_tool_call,
            "on_artifact": self.callbacks.on_artifact,
            "on_destructive_action": self.callbacks.on_destructive_action,
        }

    def _graph_run_config(self) -> dict[str, Any]:
        review_passes = max(1, self.config.policy.max_review_cycles + 1)
        replan_passes = max(1, self.config.policy.max_review_cycles + 1)
        executor_budget = self.config.policy.max_executor_iterations * review_passes * replan_passes
        return {"recursion_limit": max(25, executor_budget + 8)}

    @staticmethod
    def _recursion_error_result(state: AgentState, exc: GraphRecursionError) -> RunResult:
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
        )

    def run(self, request: RunRequest) -> RunResult:
        state = self._initial_state(request)
        graph = build_graph(self.config, self.llm, self.tools, callbacks=self._callback_map())
        try:
            stream = graph.stream(state, stream_mode="updates", config=self._graph_run_config())
            for step in stream:
                for _node_name, update in step.items():
                    if not isinstance(update, dict):
                        continue
                    if update.get("plan") and self.callbacks.on_plan:
                        self.callbacks.on_plan(dict(update["plan"]))
                    if update.get("review") and self.callbacks.on_review:
                        self.callbacks.on_review(dict(update["review"]))
                    state = _merge_state(state, update)
        except GraphRecursionError as exc:
            return self._recursion_error_result(state, exc)

        return RunResult(
            answer=str(state.get("final_answer") or state.get("draft_answer") or ""),
            review=dict(state.get("review") or {}),
            artifacts=list(state.get("artifacts") or []),
            tool_calls=list(state.get("tool_calls") or []),
            events=list(state.get("events") or []),
            error=state.get("error"),
        )

    def stream(self, request: RunRequest) -> Iterator[dict[str, Any]]:
        graph = build_graph(self.config, self.llm, self.tools, callbacks=self._callback_map())
        state = self._initial_state(request)

        yield {"type": "status", "message": "Planning..."}

        try:
            stream = graph.stream(state, stream_mode="updates", config=self._graph_run_config())
            for step in stream:
                for _node_name, update in step.items():
                    if not isinstance(update, dict):
                        continue
                    if update.get("plan") and self.callbacks.on_plan:
                        self.callbacks.on_plan(dict(update["plan"]))
                    if update.get("review") and self.callbacks.on_review:
                        self.callbacks.on_review(dict(update["review"]))

                    for event in map_graph_update(update, state):
                        if self.callbacks.on_event:
                            self.callbacks.on_event(event)
                        yield event

                    state = _merge_state(state, update)
        except GraphRecursionError as exc:
            result = self._recursion_error_result(state, exc)
            done = {
                "type": "done",
                "answer": result.answer,
                "review": result.review,
                "artifact_count": len(result.artifacts),
                "tool_call_count": len(result.tool_calls),
                "error": result.error,
            }
            if self.callbacks.on_event:
                self.callbacks.on_event(done)
            yield done
            return

        if state.get("phase") != "done":
            answer = state.get("final_answer") or state.get("draft_answer") or ""
            done = {
                "type": "done",
                "answer": answer,
                "review": state.get("review"),
                "artifact_count": len(state.get("artifacts") or []),
                "tool_call_count": len(state.get("tool_calls") or []),
                "error": state.get("error"),
            }
            if self.callbacks.on_event:
                self.callbacks.on_event(done)
            yield done
