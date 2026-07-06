from __future__ import annotations

from typing import Any

from app.agent_workflow.config import AgentConfig
from app.agent_workflow.context import ContextBuilder
from app.agent_workflow.deadlines import DeadlineExceeded, run_with_deadline
from app.agent_workflow.parsing import parse_plan_markdown
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.state import AgentState
from app.agent_workflow.telemetry import llm_call


def planner_node(state: AgentState, *, config: AgentConfig, llm: LlmProvider) -> dict[str, Any]:
    """Create or skip a plan and move the workflow into execution."""
    # The planner turns the user request into explicit steps. That keeps the
    # rest of the graph from guessing what "done" should mean.
    planner_cfg = config.policy.planner
    if not planner_cfg.enabled:
        return {
            "phase": "executing",
            "events": [{"step": "planner.skipped", "reason": "planner_disabled"}],
        }
    builder = ContextBuilder(config)
    messages = builder.build(state, "planner")
    messages[-1]["content"] += (
        "\n\nRespond using the planner markdown sections from your instructions."
    )
    try:
        raw = run_with_deadline(
            lambda: _complete_planner(llm, messages, planner_cfg.max_tokens),
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


def _complete_planner(llm: LlmProvider, messages: list[dict[str, str]], max_tokens: int) -> str:
    """Run the planner LLM call inside the debug trace wrapper."""
    with llm_call(node="planner", label="create_plan", messages=messages, max_tokens=max_tokens):
        return llm.complete(messages, max_tokens=max_tokens)
