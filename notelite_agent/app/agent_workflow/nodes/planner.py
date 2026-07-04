from __future__ import annotations

from typing import Any

from app.agent_workflow.config import AgentConfig
from app.agent_workflow.context import ContextBuilder
from app.agent_workflow.deadlines import DeadlineExceeded, run_with_deadline
from app.agent_workflow.parsing import parse_plan_markdown
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.state import AgentState


def planner_node(state: AgentState, *, config: AgentConfig, llm: LlmProvider) -> dict[str, Any]:
    builder = ContextBuilder(config)
    messages = builder.build(state, "planner")
    messages[-1]["content"] += (
        "\n\nRespond using the planner markdown sections from your instructions."
    )
    try:
        raw = run_with_deadline(
            lambda: llm.complete(messages, max_tokens=1500),
            timeout_seconds=config.policy.llm_timeout_seconds,
            label="planner LLM call",
        )
    except DeadlineExceeded as exc:
        return {
            "phase": "done",
            "final_answer": "The request timed out while creating a plan.",
            "error": str(exc),
            "events": [{"step": "planner.timeout", "error": str(exc)}],
        }
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
