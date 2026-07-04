from __future__ import annotations

from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from app.agent_workflow.config import AgentConfig
from app.agent_workflow.nodes import executor_node, planner_node, reviewer_node
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.providers.tools import ToolProvider
from app.agent_workflow.state import AgentState, Artifact


def build_graph(
    config: AgentConfig,
    llm: LlmProvider,
    tools: ToolProvider,
    callbacks: dict[str, Callable[..., Any] | None] | None = None,
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

    def _reviewer(state: AgentState) -> dict[str, Any]:
        return reviewer_node(state, config=config, llm=llm)

    graph = StateGraph(AgentState)
    graph.add_node("planner", _planner)
    graph.add_node("executor", _executor)
    graph.add_node("reviewer", _reviewer)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "executor")

    graph.add_conditional_edges(
        "executor",
        route_after_executor,
        {
            "executor": "executor",
            "reviewer": "reviewer",
            END: END,
        },
    )

    graph.add_conditional_edges(
        "reviewer",
        route_after_reviewer,
        {
            "executor": "executor",
            "planner": "planner",
            END: END,
        },
    )

    return graph.compile()


def route_after_executor(state: AgentState) -> str:
    phase = state.get("phase") or ""
    if state.get("error") and phase != "executing":
        return "reviewer"
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
