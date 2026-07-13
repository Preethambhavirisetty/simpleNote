from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import GraphRecursionError
from langgraph.types import Command

from app.agent_workflow.prompts.output_markdown import MARKDOWN_OUTPUT_RULES
from app.agent_workflow.artifact_store import get_artifact_store, is_cross_turn_persistence_active
from app.agent_workflow.conversation_memory import extract_memory_slots, get_memory_store, memory_entity_values
from app.agent_workflow.checkpointing import delete_thread, get_shared_checkpointer
from app.agent_workflow.follow_up import apply_follow_up_runtime_context, build_search_query, resolve_follow_up_policy
from app.agent_workflow.config import AgentConfig, load_agent_config, merge_agent_config, parse_agent_config
from app.agent_workflow.graph import build_graph
from app.agent_workflow.providers import OpenAiChatCompletionsProvider, create_tool_provider
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.providers.tools import ToolProvider
from app.agent_workflow.runtime_schema import RunRequestModel
from app.agent_workflow.state import AgentState
from app.agent_workflow.telemetry import begin_turn_trace, finish_turn_trace, llm_call, record_workflow_update
from app.agent_workflow.splunk_hec import log_workflow_event, log_workflow_step
from app.agent_workflow.streaming import HostCallbacks, RunRequest, RunResult, map_graph_update

from app.agent_workflow.cache import get_or_create_provider, get_or_create_graph

log = logging.getLogger(__name__)

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
    """Helper for merge state."""
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
        # A checkpointer declared in the agent config (resources.checkpointer)
        # is more specific than a host-injected default and wins; explicit
        # injection still applies for configs without a declared resource.
        """Helper for post init."""
        resource = self.config.resources.checkpointer
        if resource.mode:
            self.checkpointer = get_shared_checkpointer(resource.mode, resource.url)

        signature = self.config.signature()
        # The compiled graph closes over the llm/tools instances, so provider
        # identity must be part of the key: two engines with the same config but
        # different injected providers must not share a graph. The cached graph
        # keeps its providers alive, so these ids cannot be recycled while the
        # entry exists. (from_config/from_dict reuse cached providers per
        # signature, so the compile-once behavior for API traffic is unchanged.)
        cache_signature = f"{signature}:llm:{id(self.llm)}:tools:{id(self.tools)}"
        if self.checkpointer is not None:
            cache_signature = f"{cache_signature}:checkpointer:{id(self.checkpointer)}"

        def _build_cached() -> tuple[Any, Any]:
            """Helper for build cached."""
            checkpointer = self.checkpointer or MemorySaver()
            # ManagedCheckpointer wraps the actual saver for lifecycle control;
            # langgraph's compile() requires the raw BaseCheckpointSaver.
            saver = getattr(checkpointer, "checkpointer", None) or checkpointer
            graph = build_graph(
                self.config,
                self.llm,
                self.tools,
                callbacks=self._callback_map(),
                checkpointer=saver,
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
        """From config."""
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
        """From dict."""
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
        """From runtime config."""
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
        """Validate request and raise or return errors when invalid."""
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
        """Helper for can fast path."""
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
        router = self.config.policy.router
        if len(query) > router.fast_path_max_query_chars or len(query.split()) > router.fast_path_max_query_words:
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
        """Helper for direct answer messages."""
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "Answer the user's simple request directly and concisely. "
                    "Do not claim to have searched notes, documents, tools, or external systems.\n\n"
                    f"{MARKDOWN_OUTPUT_RULES}"
                ),
            }
        ]
        router = self.config.policy.router
        for item in request.history[-router.fast_path_history_messages :]:
            role = str(item.get("role") or "user")
            if role not in {"system", "user", "assistant"}:
                role = "user"
            messages.append(
                {"role": role, "content": str(item.get("content") or "")[: router.fast_path_history_content_chars]}
            )
        messages.append({"role": "user", "content": request.query.strip()})
        return messages

    def _fast_path_result(self, request: RunRequest, thread_id: str, reason: str) -> RunResult:
        """Helper for fast path result."""
        router = self.config.policy.router
        messages = self._direct_answer_messages(request)
        with llm_call(
            node="router",
            label="fast_path_complete",
            messages=messages,
            max_tokens=router.fast_path_max_tokens,
        ):
            answer = self.llm.complete(messages, max_tokens=router.fast_path_max_tokens).strip()
        return RunResult(
            answer=answer,
            review={"verdict": "SKIPPED", "reason": reason},
            artifacts=[],
            tool_calls=[],
            events=[{"step": "router.fast_path", "reason": reason}],
            thread_id=thread_id,
        )

    def _emit_fast_path_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Helper for emit fast path event."""
        if self.callbacks.on_event:
            self.callbacks.on_event(event)
        return event

    def _stream_fast_path(self, request: RunRequest, thread_id: str, reason: str) -> Iterator[dict[str, Any]]:
        """Helper for stream fast path."""
        yield self._emit_fast_path_event(
            {
                "type": "debug",
                "message": f"Fast path selected: {reason}",
                "thread_id": thread_id,
            }
        )
        router = self.config.policy.router
        parts: list[str] = []
        messages = self._direct_answer_messages(request)
        try:
            with llm_call(
                node="router",
                label="fast_path_stream",
                messages=messages,
                max_tokens=router.fast_path_max_tokens,
            ):
                for token in self.llm.stream(messages, max_tokens=router.fast_path_max_tokens):
                    if not token:
                        continue
                    parts.append(token)
                    yield self._emit_fast_path_event({"type": "delta", "content": token, "thread_id": thread_id})
        except Exception as exc:
            if not parts:
                with llm_call(
                    node="router",
                    label="fast_path_stream_fallback",
                    messages=messages,
                    max_tokens=router.fast_path_max_tokens,
                ):
                    answer = self.llm.complete(messages, max_tokens=router.fast_path_max_tokens).strip()
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
                "debug_trace": finish_turn_trace(),
            }
        )

    def _prepare_session(self, request: RunRequest) -> tuple[RunRequest, list[dict[str, Any]], dict[str, Any]]:
        """Load session state and apply the follow-up runtime policy for this turn.

        Conversation memory is loaded once here and threaded through the turn:
        its remembered entities feed follow-up detection (naming a known entity
        is a follow-up even when no pronoun/anchor pattern matches), and the map
        is reused for the initial state instead of re-reading the store.
        """
        policy = self.config.policy
        persistence_active = is_cross_turn_persistence_active(enabled=policy.cross_turn_artifact_persistence)
        persisted_artifacts: list[dict[str, Any]] = []
        if persistence_active and request.session_id:
            store = get_artifact_store()
            if store is not None:
                persisted_artifacts = store.load(request.session_id)
        memory = self._load_conversation_memory(request.session_id)

        follow_up = resolve_follow_up_policy(
            query=request.query,
            history=request.history,
            persisted_artifacts=persisted_artifacts,
            persistence_active=persistence_active,
            require_tool_on_follow_up=policy.require_tool_on_follow_up,
            known_entities=memory_entity_values(memory),
        )
        # Only reuse a prior turn's artifacts when this turn actually refers back
        # to it. A genuinely new question must not inherit stale facts from the
        # last turn's evidence (e.g. a weak search bleeding into the next topic).
        if not follow_up.is_follow_up:
            persisted_artifacts = []
        runtime_context = apply_follow_up_runtime_context(dict(request.runtime_context), follow_up)
        prepared = RunRequest(
            query=request.query,
            session_id=request.session_id,
            history=list(request.history),
            runtime_context=runtime_context,
        )
        return prepared, persisted_artifacts, memory

    def _clear_conversation_memory_if_new_topic(
        self,
        *,
        session_id: str,
        is_follow_up: bool,
        thread_id: str,
        prior: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Drop session memory on a new topic and surface UI/HEC telemetry when slots existed.

        ``prior`` is the map _prepare_session already loaded — no second read.
        """
        policy = self.config.policy
        if is_follow_up or not policy.enable_conversation_memory:
            return None
        session_id = str(session_id or "").strip()
        if not session_id or not prior:
            return None
        get_memory_store().delete(session_id)
        cleared_slots = sorted(str(key) for key in prior.keys())
        log_workflow_event(
            thread_id=thread_id,
            session_id=session_id,
            kind="memory.cleared",
            data={"slot_count": len(prior), "cleared_slots": cleared_slots},
        )
        return {
            "type": "agent_activity",
            "label": "memory.cleared",
            "thread_id": thread_id,
            "slot_count": len(prior),
            "cleared_slots": cleared_slots,
        }

    def _follow_up_reuse_event(self, request: RunRequest, persisted_artifacts: list[dict[str, Any]], thread_id: str) -> dict[str, Any] | None:
        """Decide whether this follow-up can answer from persisted session evidence.

        Returns the UI activity event when the shortcut applies (the caller then
        starts the graph at fact extraction), else None. Applies only when the
        turn is a follow-up that does NOT require fresh tool recall and evidence
        from earlier turns is already loaded — e.g. re-asking about the same
        dashboard should not replan and re-explore from scratch.
        """
        if not self.config.policy.enable_follow_up_reuse:
            return None
        runtime = request.runtime_context or {}
        if not runtime.get("follow_up") or runtime.get("require_tools"):
            return None
        if not persisted_artifacts:
            return None
        tools = sorted({str(a.get("tool") or "") for a in persisted_artifacts if a.get("tool")})
        log_workflow_event(
            thread_id=thread_id,
            session_id=request.session_id,
            kind="run.follow_up_reuse",
            data={"artifact_count": len(persisted_artifacts), "tools": tools},
        )
        return {
            "type": "agent_activity",
            "phase": "running",
            "label": (
                f"Follow-up: answering from {len(persisted_artifacts)} result(s) gathered earlier this session"
                + (f" ({', '.join(tools[:4])})" if tools else "")
            ),
            "artifact_count": len(persisted_artifacts),
            "tools": tools,
            "thread_id": thread_id,
        }

    def _initial_state(
        self,
        request: RunRequest,
        *,
        persisted_artifacts: list[dict[str, Any]] | None = None,
        conversation_memory: dict[str, Any] | None = None,
        reuse_evidence: bool = False,
    ) -> AgentState:
        """Helper for initial state.

        ``conversation_memory`` short-circuits the store load when the caller
        already knows the slots (e.g. {} right after a new-topic clear).
        ``reuse_evidence`` starts the run at fact extraction so a follow-up
        answers from the persisted artifacts instead of replanning.
        """
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
        if reuse_evidence:
            # Enter the graph at fact extraction: the persisted artifacts are the
            # evidence, so the run goes straight to synthesis + review. If the
            # reviewer finds the evidence lacking, re-explore falls back into the
            # executor with its usual bounds.
            phase = "fact_extracting"

        return AgentState(
            messages=list(request.history),
            user_query=request.query.strip(),
            # Deterministic standalone-query fallback. The planner overwrites this
            # with its history-aware rewrite when enabled; when the planner is
            # disabled it is the only source, so it must be set here.
            search_query=build_search_query(request.query.strip(), list(request.history)),
            session_id=request.session_id,
            runtime_context=dict(request.runtime_context),
            plan=plan,
            current_step_index=0,
            candidate_tools=[],
            tool_discovery_cache={},
            artifacts=list(persisted_artifacts or []),
            conversation_memory=(
                conversation_memory
                if conversation_memory is not None
                else self._load_conversation_memory(request.session_id)
            ),
            tool_calls=[],
            facts=[],
            draft_answer="",
            draft_kind="",
            executor_guidance=[],
            review={},
            review_feedback="",
            iteration={"executor_turns": 0, "review_cycles": 0, "revision_cycles": 0, "tool_calls": 0},
            events=(
                [{"step": "router.follow_up_reuse", "artifact_count": len(persisted_artifacts or [])}]
                if reuse_evidence
                else []
            ),
            phase=phase,
            final_answer="",
            error=None,
            pending_destructive=None,
        )

    def _callback_map(self) -> dict[str, Any]:
        """Call callback map and return the provider result."""
        return {
            "on_tool_search": self.callbacks.on_tool_search,
            "on_tool_call": self.callbacks.on_tool_call,
            "on_artifact": self.callbacks.on_artifact,
            "on_destructive_action": self.callbacks.on_destructive_action,
        }

    def _new_thread_id(self, session_id: str) -> str:
        # Unique per run: reusing a conversation-scoped id verbatim would collide
        # with the previous turn's checkpoint (including a paused interrupt).
        """Helper for new thread id."""
        return f"{session_id or 'run'}-{uuid.uuid4().hex[:12]}"

    def _thread_config(self, thread_id: str) -> dict[str, Any]:
        """Helper for thread config."""
        review_cycles = max(0, self.config.policy.reviewer.max_cycles)
        explore_cycles = max(0, self.config.policy.max_explore_cycles)
        # Reviewer-driven re-exploration re-enters the executor loop, so its
        # bounded cycles add to the recursion budget alongside review passes.
        review_passes = max(1, review_cycles + explore_cycles + 1)
        # Each pass also visits the non-executor pipeline (summarizer,
        # fact_extractor, synthesizer, reviewer, revision, finalizer). LangGraph's
        # recursion_limit counts every node visit, so budget that per-pass
        # overhead too — otherwise a heavy config trips GraphRecursionError mid-run
        # well before the executor iteration caps are actually reached.
        per_pass_node_overhead = 12
        executor_budget = review_passes * (self.config.policy.max_executor_iterations + per_pass_node_overhead)
        return {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": max(25, executor_budget + 24),
        }

    @staticmethod
    def _awaiting_answer(pending: dict[str, Any]) -> str:
        """Helper for awaiting answer."""
        tool = pending.get("tool") or "a destructive tool"
        return (
            f"This request needs an action that requires approval: {tool}. "
            "The run is paused until the action is approved or denied."
        )

    def _recursion_error_result(self, state: AgentState, exc: GraphRecursionError, thread_id: str) -> RunResult:
        """Helper for recursion error result."""
        answer = str(state.get("final_answer") or state.get("draft_answer") or "")
        if not answer and state.get("artifacts"):
            from app.agent_workflow.nodes.executor import _fallback_answer

            answer = _fallback_answer(state, config=self.config)
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
        """Helper for pending events from interrupt."""
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
            # With stream_mode=["updates", "custom"] each item is (mode, payload).
            if isinstance(step, tuple) and len(step) == 2:
                mode, payload = step
                if mode == "custom":
                    if isinstance(payload, dict) and payload.get("type") == "delta":
                        event = {**payload, "thread_id": thread_id}
                        if self.callbacks.on_event:
                            self.callbacks.on_event(event)
                        yield event
                    continue
                step = payload
            if not isinstance(step, dict):
                continue
            for node_name, update in step.items():
                if node_name == "__interrupt__":
                    yield from self._pending_events_from_interrupt(update, thread_id)
                    continue
                if isinstance(update, dict) and "__interrupt__" in update:
                    yield from self._pending_events_from_interrupt(update["__interrupt__"], thread_id)
                    continue
                if not isinstance(update, dict):
                    continue
                record_workflow_update(update, holder["state"])
                if update.get("plan") and self.callbacks.on_plan:
                    self.callbacks.on_plan(dict(update["plan"]))
                if update.get("review") and self.callbacks.on_review:
                    self.callbacks.on_review(dict(update["review"]))

                for event in map_graph_update(update, holder["state"], node_name=node_name):
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

                # Stream a per-step log to Splunk HEC in the background (no-op
                # when disabled; enqueue never blocks the agent loop).
                log_workflow_step(
                    thread_id=thread_id,
                    session_id=str(holder["state"].get("session_id") or ""),
                    node=node_name,
                    update=update,
                    state=holder["state"],
                )

    @staticmethod
    def _pending_approval_event(state: AgentState, thread_id: str) -> dict[str, Any] | None:
        """Helper for pending approval event."""
        pending = state.get("pending_destructive")
        if state.get("phase") != "awaiting_approval" or not pending:
            return None
        event = {"type": "pending_approval", "thread_id": thread_id}
        event.update(dict(pending))
        return event

    @staticmethod
    def _error_result(thread_id: str, error: str) -> RunResult:
        """Helper for error result."""
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

    def _persist_session_artifacts(self, state: AgentState) -> None:
        """Save pruned artifacts for cross-turn reuse when persistence is active.

        Session is read from state so every terminal path (run, stream, and the
        post-approval resume) persists uniformly.
        """
        policy = self.config.policy
        if not is_cross_turn_persistence_active(enabled=policy.cross_turn_artifact_persistence):
            return
        if state.get("phase") == "awaiting_approval" or state.get("pending_destructive"):
            return
        session_id = str(state.get("session_id") or "")
        if not session_id:
            return
        store = get_artifact_store()
        if store is None:
            return
        artifacts = list(state.get("artifacts") or [])
        max_items = max(0, int(policy.max_retained_artifacts or 0))
        if max_items and len(artifacts) > max_items:
            artifacts = sorted(
                artifacts,
                key=lambda item: float(item.get("composite_score") or item.get("score") or 0.0),
                reverse=True,
            )[:max_items]
        store.save(
            session_id,
            artifacts,
            ttl_seconds=policy.artifact_store_ttl_seconds,
        )

    def _load_conversation_memory(self, session_id: str) -> dict[str, Any]:
        """Load this session's established-entity slots (empty when disabled)."""
        if not self.config.policy.enable_conversation_memory or not session_id:
            return {}
        try:
            return get_memory_store().load(session_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("conversation memory load skipped: %s", exc)
            return {}

    def _update_conversation_memory(
        self, state: AgentState, thread_id: str
    ) -> dict[str, Any] | None:
        """Merge this turn's entities into session memory for later follow-ups.

        Runs once per turn at engine level (outside the graph). Persists the slot
        map and, when something new was learned, streams a ``memory.updated``
        record to Splunk HEC and returns an ``agent_activity`` event for the UI.
        Session and turn are read from state so it serves the run, stream, and
        post-approval resume paths uniformly.
        """
        policy = self.config.policy
        session_id = str(state.get("session_id") or "")
        if not policy.enable_conversation_memory or not session_id:
            return None
        if state.get("phase") == "awaiting_approval" or state.get("pending_destructive"):
            return None
        prior = state.get("conversation_memory") or {}
        turn = len(state.get("messages") or []) + 1
        updated = extract_memory_slots(
            prior,
            state,
            turn=turn,
            max_slots=policy.conversation_memory_max_slots,
        )
        if not updated:
            return None
        state["conversation_memory"] = updated
        # Compute the delta before writing so an unchanged turn skips the store
        # round-trip (and emits no event) entirely.
        changed = [
            f"{key}={slot.get('value')}"
            for key, slot in updated.items()
            if not isinstance(prior.get(key), dict) or prior[key].get("value") != slot.get("value")
        ]
        if not changed:
            return None
        try:
            get_memory_store().save(
                session_id,
                updated,
                ttl_seconds=policy.artifact_store_ttl_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("conversation memory save skipped: %s", exc)
        log_workflow_event(
            thread_id=thread_id,
            session_id=session_id,
            kind="memory.updated",
            data={"slot_count": len(updated), "updated_slots": changed},
        )
        return {
            "type": "agent_activity",
            "label": "memory.updated",
            "thread_id": thread_id,
            "slot_count": len(updated),
            "updated_slots": changed,
        }

    def _emit(self, event: dict[str, Any] | None) -> None:
        """Deliver an out-of-graph event to the host callback when present."""
        if event and self.callbacks.on_event:
            self.callbacks.on_event(event)

    def _emit_and_yield(self, event: dict[str, Any] | None) -> Iterator[dict[str, Any]]:
        """Emit an optional event to callbacks and yield it into the stream."""
        if event is not None:
            self._emit(event)
            yield event

    def _final_event_with_usage(
        self, state: AgentState, thread_id: str, usage_start: dict[str, int]
    ) -> dict[str, Any] | None:
        """Build the terminal stream event with LLM usage and the debug trace."""
        final = self._final_event(state, thread_id)
        if final is None:
            return None
        usage = self._llm_usage_delta(usage_start, self._llm_usage_snapshot())
        if usage:
            final["usage"] = usage
        final["debug_trace"] = finish_turn_trace()
        return final

    def _finalize_turn(
        self,
        state: AgentState,
        thread_id: str,
        *,
        result: RunResult,
        session_id: str,
        cleanup_terminal: bool = True,
    ) -> None:
        """Run the shared end-of-turn side effects (persist, cleanup, run log).

        One definition for every terminal path — run/stream/resume, normal and
        recursion — so turn teardown cannot drift between them again. The
        caller's result is logged as-is (recursion paths carry their own error).
        """
        self._persist_session_artifacts(state)
        if cleanup_terminal:
            self._cleanup_thread_if_terminal(state, thread_id)
        self._log_run_completed(result, session_id=session_id)

    def _cleanup_thread_if_terminal(self, state: AgentState, thread_id: str) -> None:
        """Helper for cleanup thread if terminal."""
        if state.get("phase") == "awaiting_approval" or state.get("pending_destructive"):
            return
        delete_thread(self.checkpointer, thread_id)

    def _result_from_state(self, state: AgentState, thread_id: str) -> RunResult:
        """Helper for result from state."""
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
        """Helper for llm usage snapshot."""
        usage = getattr(self.llm, "usage_totals", None)
        if not callable(usage):
            return {}
        try:
            return {str(k): int(v) for k, v in usage().items()}
        except Exception:  # noqa: BLE001
            return {}

    @staticmethod
    def _llm_usage_delta(start: dict[str, int], end: dict[str, int]) -> dict[str, int]:
        """Helper for llm usage delta."""
        keys = set(start) | set(end)
        return {key: max(0, int(end.get(key, 0)) - int(start.get(key, 0))) for key in keys}

    def _attach_usage_event(self, result: RunResult, usage_start: dict[str, int]) -> RunResult:
        """Helper for attach usage event."""
        usage = self._llm_usage_delta(usage_start, self._llm_usage_snapshot())
        if usage:
            result.events.append({"step": "telemetry.llm_usage", "usage": usage})
        result.events.extend(finish_turn_trace())
        return result

    # ── public API ─────────────────────────────────────────────────────────────

    def run(self, request: RunRequest) -> RunResult:
        """Run one request synchronously and return the final workflow result."""
        request = self._validate_request(request)
        thread_id = self._new_thread_id(request.session_id)
        begin_turn_trace(thread_id, request.query)
        log_workflow_event(thread_id=thread_id, session_id=request.session_id, kind="run.started", data={"query": request.query[:500], "mode": "sync"})
        fast_path, reason = self._can_fast_path(request)
        if fast_path:
            usage_start = self._llm_usage_snapshot()
            log_workflow_event(thread_id=thread_id, session_id=request.session_id, kind="run.fast_path", data={"reason": reason})
            return self._attach_usage_event(self._fast_path_result(request, thread_id, reason), usage_start)
        request, persisted_artifacts, memory = self._prepare_session(request)
        is_follow_up = bool((request.runtime_context or {}).get("follow_up"))
        self._emit(
            self._clear_conversation_memory_if_new_topic(
                session_id=request.session_id,
                is_follow_up=is_follow_up,
                thread_id=thread_id,
                prior=memory,
            )
        )
        reuse_event = self._follow_up_reuse_event(request, persisted_artifacts, thread_id)
        self._emit(reuse_event)
        holder = {
            "state": self._initial_state(
                request,
                persisted_artifacts=persisted_artifacts,
                # Memory was loaded once in _prepare_session; a new topic just
                # cleared it, so the state starts empty in that case.
                conversation_memory=memory if is_follow_up else {},
                reuse_evidence=reuse_event is not None,
            )
        }
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
            self._emit(self._update_conversation_memory(holder["state"], thread_id))
            self._finalize_turn(holder["state"], thread_id, result=result, session_id=request.session_id)
            return result
        result = self._result_from_state(holder["state"], thread_id)
        self._attach_usage_event(result, usage_start)
        self._emit(self._update_conversation_memory(holder["state"], thread_id))
        self._finalize_turn(holder["state"], thread_id, result=result, session_id=request.session_id)
        return result

    @staticmethod
    def _log_run_completed(result: RunResult, *, session_id: str = "") -> None:
        """Emit a run-boundary log to Splunk (no-op when disabled).

        The single shape used by every terminal path (run, stream, resume) so the
        run.completed record does not vary by exit route.
        """
        log_workflow_event(
            thread_id=result.thread_id,
            session_id=session_id,
            kind="run.completed",
            data={
                "answer_chars": len(result.answer or ""),
                "verdict": (result.review or {}).get("verdict"),
                "artifact_count": len(result.artifacts),
                "tool_call_count": len(result.tool_calls),
                "pending_approval": bool(result.pending_approval),
                "error": result.error,
            },
        )

    def stream(self, request: RunRequest) -> Iterator[dict[str, Any]]:
        """Run one streaming LLM completion request."""
        request = self._validate_request(request)
        thread_id = self._new_thread_id(request.session_id)
        begin_turn_trace(thread_id, request.query)
        log_workflow_event(thread_id=thread_id, session_id=request.session_id, kind="run.started", data={"query": request.query[:500], "mode": "stream"})
        fast_path, reason = self._can_fast_path(request)
        if fast_path:
            log_workflow_event(thread_id=thread_id, session_id=request.session_id, kind="run.fast_path", data={"reason": reason})
            yield from self._stream_fast_path(request, thread_id, reason)
            return

        request, persisted_artifacts, memory = self._prepare_session(request)
        is_follow_up = bool((request.runtime_context or {}).get("follow_up"))
        yield from self._emit_and_yield(
            self._clear_conversation_memory_if_new_topic(
                session_id=request.session_id,
                is_follow_up=is_follow_up,
                thread_id=thread_id,
                prior=memory,
            )
        )
        reuse_event = self._follow_up_reuse_event(request, persisted_artifacts, thread_id)
        yield from self._emit_and_yield(reuse_event)
        holder = {
            "state": self._initial_state(
                request,
                persisted_artifacts=persisted_artifacts,
                # Memory was loaded once in _prepare_session; a new topic just
                # cleared it, so the state starts empty in that case.
                conversation_memory=memory if is_follow_up else {},
                reuse_evidence=reuse_event is not None,
            )
        }
        usage_start = self._llm_usage_snapshot()
        yielded_pending_approval = False
        streamed_answer = False

        status = "Answering from session evidence..." if reuse_event is not None else "Planning..."
        yield {"type": "status", "message": status, "thread_id": thread_id}

        stream = None
        try:
            stream = self.graph.stream(
                holder["state"], stream_mode=["updates", "custom"], config=self._thread_config(thread_id)
            )
            for event in self._pump(stream, holder, thread_id, emit_done=False):
                if event.get("type") == "pending_approval":
                    yielded_pending_approval = True
                if event.get("type") == "delta":
                    streamed_answer = True
                yield event
        except GeneratorExit:
            if stream is not None and hasattr(stream, "close"):
                stream.close()
            if self.callbacks.on_event:
                self.callbacks.on_event({"type": "debug", "message": "Run cancelled by client disconnect", "thread_id": thread_id})
            self._cleanup_thread_if_terminal(holder["state"], thread_id)
            raise
        except GraphRecursionError as exc:
            result = self._recursion_error_result(holder["state"], exc, thread_id)
            yield from self._emit_and_yield(self._update_conversation_memory(holder["state"], thread_id))
            yield self._done_event_from_result(result)
            self._finalize_turn(holder["state"], thread_id, result=result, session_id=request.session_id)
            return

        pending_event = self._pending_approval_event(holder["state"], thread_id)
        if pending_event is not None and not yielded_pending_approval:
            if self.callbacks.on_event:
                self.callbacks.on_event(pending_event)
            yield pending_event

        if pending_event is None and not streamed_answer:
            answer = str(holder["state"].get("final_answer") or holder["state"].get("draft_answer") or "")
            if answer:
                event = {"type": "delta", "content": answer, "thread_id": thread_id}
                if self.callbacks.on_event:
                    self.callbacks.on_event(event)
                yield event

        yield from self._emit_and_yield(self._update_conversation_memory(holder["state"], thread_id))
        yield from self._emit_and_yield(self._final_event_with_usage(holder["state"], thread_id, usage_start))
        self._finalize_turn(
            holder["state"],
            thread_id,
            result=self._result_from_state(holder["state"], thread_id),
            session_id=request.session_id,
        )

    def resume(self, thread_id: str, *, approved: bool) -> RunResult:
        """Resume a paused destructive-approval workflow and return its result."""
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

        begin_turn_trace(thread_id, str(state.get("user_query") or "resume"))
        holder = {"state": state}
        usage_start = self._llm_usage_snapshot()
        streamed_answer = False
        try:
            stream = self.graph.stream(
                Command(resume={"approved": approved}), stream_mode=["updates", "custom"], config=config
            )
            for event in self._pump(stream, holder, thread_id, emit_done=False):
                if event.get("type") == "delta":
                    streamed_answer = True
                yield event
        except GraphRecursionError as exc:
            result = self._recursion_error_result(holder["state"], exc, thread_id)
            yield self._done_event_from_result(result)
            self._finalize_turn(
                holder["state"],
                thread_id,
                result=result,
                session_id=str(holder["state"].get("session_id") or ""),
                cleanup_terminal=cleanup_terminal,
            )
            return

        if not holder["state"].get("pending_destructive") and not streamed_answer:
            answer = str(holder["state"].get("final_answer") or holder["state"].get("draft_answer") or "")
            if answer:
                event = {"type": "delta", "content": answer, "thread_id": thread_id}
                if self.callbacks.on_event:
                    self.callbacks.on_event(event)
                yield event

        yield from self._emit_and_yield(self._update_conversation_memory(holder["state"], thread_id))
        yield from self._emit_and_yield(self._final_event_with_usage(holder["state"], thread_id, usage_start))
        self._finalize_turn(
            holder["state"],
            thread_id,
            result=self._result_from_state(holder["state"], thread_id),
            session_id=str(holder["state"].get("session_id") or ""),
            cleanup_terminal=cleanup_terminal,
        )

    @staticmethod
    def _done_event_from_result(result: RunResult) -> dict[str, Any]:
        """Helper for done event from result."""
        return {
            "type": "done",
            "answer": result.answer,
            "review": result.review,
            "artifact_count": len(result.artifacts),
            "tool_call_count": len(result.tool_calls),
            "error": result.error,
            "thread_id": result.thread_id,
            "debug_trace": finish_turn_trace(),
        }
