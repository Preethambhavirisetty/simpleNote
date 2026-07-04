from __future__ import annotations

from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from app.agent_workflow.config import AgentConfig
from app.agent_workflow.nodes import approval_node, executor_node, planner_node, reviewer_node
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.providers.tools import ToolProvider
from app.agent_workflow.state import AgentState, Artifact


def build_graph(
    config: AgentConfig,
    llm: LlmProvider,
    tools: ToolProvider,
    callbacks: dict[str, Callable[..., Any] | None] | None = None,
    checkpointer: Any = None,
):
    callbacks = callbacks or {}

    def _planner(state: AgentState) -> dict[str, Any]:
        return planner_node(state, config=config, llm=llm)

    def _executor(state: AgentState) -> dict[str, Any]:
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
        return approval_node(
            state,
            config=config,
            tools=tools,
            on_tool_call=callbacks.get("on_tool_call"),
            on_artifact=callbacks.get("on_artifact"),
        )

    def _reviewer(state: AgentState) -> dict[str, Any]:
        return reviewer_node(state, config=config, llm=llm)

    graph = StateGraph(AgentState)
    graph.add_node("planner", _planner)
    graph.add_node("executor", _executor)
    graph.add_node("approval", _approval)
    graph.add_node("reviewer", _reviewer)

    graph.add_conditional_edges(
        START,
        route_after_start,
        {
            "planner": "planner",
            "executor": "executor",
        },
    )
    graph.add_edge("planner", "executor")

    graph.add_conditional_edges(
        "executor",
        lambda state: route_after_executor(state, config=config),
        {
            "executor": "executor",
            "approval": "approval",
            "reviewer": "reviewer",
            END: END,
        },
    )

    # The approval node always hands control back to the executor: it either
    # executed the approved call or recorded the denial, and phase="executing".
    graph.add_edge("approval", "executor")

    graph.add_conditional_edges(
        "reviewer",
        route_after_reviewer,
        {
            "executor": "executor",
            "planner": "planner",
            END: END,
        },
    )

    return graph.compile(checkpointer=checkpointer)


def route_after_start(state: AgentState) -> str:
    return "executor" if (state.get("phase") or "") == "executing" else "planner"


def route_after_executor(state: AgentState, *, config: AgentConfig) -> str:
    phase = state.get("phase") or ""
    if phase == "awaiting_approval":
        return "approval"
    if phase == "reviewing" and not config.policy.enable_reviewer:
        return END
    if state.get("error") and phase != "executing":
        return "reviewer" if config.policy.enable_reviewer else END
    if phase == "reviewing":
        return "reviewer"
    if phase == "executing":
        return "executor"
    return END


def route_after_reviewer(state: AgentState) -> str:
    phase = state.get("phase") or ""
    review = state.get("review") or {}
    verdict = review.get("verdict", "")

    if phase == "planning" and verdict == "REJECT":
        return "planner"
    if phase == "executing" and verdict == "REVISE":
        return "executor"
    return END
