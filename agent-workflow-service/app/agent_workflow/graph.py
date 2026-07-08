from __future__ import annotations

from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from app.agent_workflow.config import AgentConfig
from app.agent_workflow.nodes import (
    approval_node,
    executor_node,
    fact_extractor_node,
    finalizer_node,
    planner_node,
    reviewer_node,
    revision_node,
    summarizer_node,
    synthesizer_node,
)
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.providers.tools import ToolProvider
from app.agent_workflow.state import AgentState


def build_graph(
    config: AgentConfig,
    llm: LlmProvider,
    tools: ToolProvider,
    callbacks: dict[str, Callable[..., Any] | None] | None = None,
    checkpointer: Any = None,
):
    """Build the LangGraph workflow and wire each node to its router."""
    callbacks = callbacks or {}

    def _planner(state: AgentState) -> dict[str, Any]:
        """Helper for planner."""
        return planner_node(state, config=config, llm=llm)

    def _executor(state: AgentState) -> dict[str, Any]:
        """Helper for executor."""
        return executor_node(
            state,
            config=config,
            llm=llm,
            tools=tools,
            on_tool_search=callbacks.get("on_tool_search"),
            on_tool_call=callbacks.get("on_tool_call"),
            on_artifact=callbacks.get("on_artifact"),
            on_destructive_action=callbacks.get("on_destructive_action"),
        )

    def _approval(state: AgentState) -> dict[str, Any]:
        """Helper for approval."""
        return approval_node(
            state,
            config=config,
            tools=tools,
            on_tool_call=callbacks.get("on_tool_call"),
            on_artifact=callbacks.get("on_artifact"),
        )

    def _fact_extractor(state: AgentState) -> dict[str, Any]:
        """Extract compact facts from raw tool artifacts."""
        return fact_extractor_node(state, config=config)

    def _summarizer(state: AgentState) -> dict[str, Any]:
        """Compress accumulated artifacts into running memory mid-loop."""
        return summarizer_node(state, config=config, llm=llm)

    def _synthesizer(state: AgentState) -> dict[str, Any]:
        """Write the main draft answer from facts."""
        return synthesizer_node(state, config=config, llm=llm)

    def _reviewer(state: AgentState) -> dict[str, Any]:
        """Judge the draft without rewriting it."""
        return reviewer_node(state, config=config, llm=llm)

    def _revision(state: AgentState) -> dict[str, Any]:
        """Apply one bounded revision using the same facts."""
        return revision_node(state, config=config, llm=llm)

    def _finalizer(state: AgentState) -> dict[str, Any]:
        """Render or reuse the terminal answer."""
        return finalizer_node(state, config=config, llm=llm)

    # The graph is deliberately small: each node owns one phase, and routing
    # is driven by state["phase"] plus reviewer verdicts.
    graph = StateGraph(AgentState)
    graph.add_node("planner", _planner)
    graph.add_node("executor", _executor)
    graph.add_node("approval", _approval)
    graph.add_node("fact_extractor", _fact_extractor)
    graph.add_node("summarizer", _summarizer)
    graph.add_node("synthesizer", _synthesizer)
    graph.add_node("reviewer", _reviewer)
    graph.add_node("revision", _revision)
    graph.add_node("finalizer", _finalizer)

    graph.add_conditional_edges(
        START,
        route_after_start,
        {
            "planner": "planner",
            "executor": "executor",
        },
    )
    graph.add_conditional_edges(
        "planner",
        route_after_planner,
        {
            "executor": "executor",
            "finalizer": "finalizer",
            END: END,
        },
    )

    graph.add_conditional_edges(
        "executor",
        lambda state: route_after_executor(state, config=config),
        {
            "executor": "executor",
            "approval": "approval",
            "summarizer": "summarizer",
            "fact_extractor": "fact_extractor",
            "finalizer": "finalizer",
            END: END,
        },
    )

    # The summarizer is a mid-loop detour: it compresses memory and hands control
    # straight back to the executor to keep gathering evidence.
    graph.add_edge("summarizer", "executor")

    # Approval is only for pending destructive side effects; normal read/report
    # tasks skip it entirely and continue through executor.
    graph.add_edge("approval", "executor")

    graph.add_edge("fact_extractor", "synthesizer")

    graph.add_conditional_edges(
        "synthesizer",
        route_after_synthesizer,
        {
            "reviewer": "reviewer",
            "finalizer": "finalizer",
            END: END,
        },
    )

    graph.add_conditional_edges(
        "reviewer",
        route_after_reviewer,
        {
            "executor": "executor",
            "revision": "revision",
            "finalizer": "finalizer",
            END: END,
        },
    )

    graph.add_edge("revision", "finalizer")
    graph.add_edge("finalizer", END)

    return graph.compile(checkpointer=checkpointer)


def route_after_planner(state: AgentState) -> str:
    """Choose the next node after planning based on the current phase."""
    return "finalizer" if (state.get("phase") or "") == "done" else "executor"


def route_after_start(state: AgentState) -> str:
    """Choose whether a run starts with planning or direct execution."""
    return "executor" if (state.get("phase") or "") == "executing" else "planner"


def route_after_executor(state: AgentState, *, config: AgentConfig) -> str:
    """Route executor updates to approval, another executor turn, or fact extraction."""
    # Executor owns tool orchestration only. Once it has enough work product, it
    # hands off to deterministic fact extraction instead of synthesizing/reviewing.
    phase = state.get("phase") or ""
    if phase == "awaiting_approval":
        return "approval"
    if phase == "fact_extracting":
        return "fact_extractor"
    if phase == "executing":
        # Compress memory mid-loop when retained artifacts approach the cap, then
        # return to the executor with freed context for more exploration.
        return "summarizer" if _should_compact(state, config) else "executor"
    # Any other phase (including "done" and unexpected values) finalizes; the
    # finalizer emits an error for phases that should never reach it.
    return "finalizer"


def _should_compact(state: AgentState, config: AgentConfig) -> bool:
    """Return whether the executor loop should detour through the summarizer."""
    policy = config.policy
    if not policy.enable_running_summary:
        return False
    iteration = state.get("iteration") or {}
    if int(iteration.get("summaries") or 0) >= policy.summary.max_cycles:
        return False
    return len(state.get("artifacts") or []) >= policy.summary.compact_after_artifacts


def route_after_synthesizer(state: AgentState) -> str:
    """Route the synthesized draft either to review or finalization."""
    phase = state.get("phase") or ""
    if phase == "reviewing":
        return "reviewer"
    # "done" and any unexpected phase both finalize safely.
    return "finalizer"


def route_after_reviewer(state: AgentState) -> str:
    """Route reviewer verdicts to re-exploration, one revision, or finalization."""
    phase = state.get("phase") or ""
    if phase == "executing":
        # Evidence-revise: re-enter the executor (bounded) to gather missing tools.
        return "executor"
    if phase == "revising":
        return "revision"
    # "done" and any unexpected phase both finalize safely.
    return "finalizer"
