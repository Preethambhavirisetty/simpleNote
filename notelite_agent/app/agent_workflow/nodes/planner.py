from __future__ import annotations

from typing import Any

from app.agent_workflow.config import AgentConfig
from app.agent_workflow.context import ContextBuilder
from app.agent_workflow.parsing import parse_plan_markdown
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.state import AgentState


def planner_node(state: AgentState, *, config: AgentConfig, llm: LlmProvider) -> dict[str, Any]:
    builder = ContextBuilder(config)
    messages = builder.build(state, "planner")
    messages[-1]["content"] += (
        "\n\nRespond using the planner markdown sections from your instructions."
    )
    raw = llm.complete(messages, max_tokens=1500)
    plan = parse_plan_markdown(raw)
    iteration = dict(state.get("iteration") or {})
    iteration["executor_turns"] = 0
    return {
        "plan": plan,
        "phase": "executing",
        "current_step_index": 0,
        "candidate_tools": [],
        "review_feedback": "",
        "events": [{"step": "planner.completed", "goal": plan.get("goal", "")}],
        "iteration": iteration,
    }
