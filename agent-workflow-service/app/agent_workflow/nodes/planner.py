from __future__ import annotations

from typing import Any

from app.agent_workflow.config import AgentConfig
from app.agent_workflow.context import ContextBuilder
from app.agent_workflow.deadlines import DeadlineExceeded, run_with_deadline
from app.agent_workflow.follow_up import build_search_query
from app.agent_workflow.parsing import enrich_plan_with_evidence, parse_plan_markdown
from app.agent_workflow.playbooks.router import resolve_playbook_plan
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.state import AgentState
from app.agent_workflow.telemetry import llm_call


def planner_node(state: AgentState, *, config: AgentConfig, llm: LlmProvider) -> dict[str, Any]:
    """Create or skip a plan and move the workflow into execution."""
    # The planner turns the user request into explicit steps. That keeps the
    # rest of the graph from guessing what "done" should mean.
    fallback_query = build_search_query(str(state.get("user_query") or ""), state.get("messages") or [])
    planner_cfg = config.policy.planner
    if not planner_cfg.enabled:
        return {
            "phase": "executing",
            "search_query": fallback_query,
            "events": [{"step": "planner.skipped", "reason": "planner_disabled"}],
        }

    if config.policy.enable_playbooks:
        playbook_plan = resolve_playbook_plan(str(state.get("user_query") or ""))
        if playbook_plan:
            iteration = dict(state.get("iteration") or {})
            iteration["executor_turns"] = 0
            search_query = str(playbook_plan.get("search_query") or "").strip() or fallback_query
            return {
                "plan": enrich_plan_with_evidence(playbook_plan),
                "phase": "executing",
                "search_query": search_query,
                "current_step_index": 0,
                "candidate_tools": [],
                "review_feedback": "",
                "events": [
                    {
                        "step": "planner.playbook",
                        "playbook_id": playbook_plan.get("playbook_id", ""),
                        "goal": playbook_plan.get("goal", ""),
                    }
                ],
                "iteration": iteration,
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
    plan = enrich_plan_with_evidence(plan)
    iteration = dict(state.get("iteration") or {})
    iteration["executor_turns"] = 0
    # Prefer the planner's history-aware rewrite; fall back to the deterministic
    # standalone query so tool search always has resolved nouns.
    search_query = str(plan.get("search_query") or "").strip() or fallback_query
    return {
        "plan": plan,
        "phase": "executing",
        "search_query": search_query,
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
