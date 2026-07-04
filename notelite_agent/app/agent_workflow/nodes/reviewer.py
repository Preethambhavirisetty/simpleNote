from __future__ import annotations

from typing import Any

from app.agent_workflow.config import AgentConfig
from app.agent_workflow.context import ContextBuilder
from app.agent_workflow.deadlines import DeadlineExceeded, run_with_deadline
from app.agent_workflow.parsing import parse_review_markdown
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.state import AgentState


def reviewer_node(state: AgentState, *, config: AgentConfig, llm: LlmProvider) -> dict[str, Any]:
    iteration = dict(state.get("iteration") or {})
    iteration["review_cycles"] = int(iteration.get("review_cycles") or 0) + 1

    builder = ContextBuilder(config)
    messages = builder.build(state, "reviewer")
    messages[-1]["content"] += "\n\nRespond using the reviewer markdown sections from your instructions."

    try:
        raw = run_with_deadline(
            lambda: llm.complete(messages, max_tokens=1200),
            timeout_seconds=config.policy.llm_timeout_seconds,
            label="reviewer LLM call",
        )
    except DeadlineExceeded as exc:
        return {
            "phase": "done",
            "final_answer": state.get("draft_answer") or "The request timed out during review.",
            "review": {"verdict": "SKIPPED", "reason": "review_timeout"},
            "iteration": iteration,
            "error": str(exc),
            "events": [{"step": "reviewer.timeout", "error": str(exc)}],
        }
    review = parse_review_markdown(raw)

    updates: dict[str, Any] = {
        "review": review,
        "iteration": iteration,
        "phase": "done" if review.get("verdict") == "APPROVE" else "executing",
    }

    verdict = review.get("verdict", "REVISE")
    if verdict == "APPROVE":
        approved = review.get("approved_answer") or state.get("draft_answer") or ""
        updates["final_answer"] = approved.strip()
        updates["error"] = None
    elif verdict == "REVISE":
        required = review.get("required_changes") or []
        updates["review_feedback"] = "\n".join(f"- {item}" for item in required)
        iteration["executor_turns"] = 0
        updates["iteration"] = iteration
        if iteration["review_cycles"] >= config.policy.max_review_cycles:
            from app.agent_workflow.nodes.executor import _fallback_answer

            updates["final_answer"] = state.get("draft_answer") or _fallback_answer(state)
            updates["phase"] = "done"
            updates["error"] = "Review cycle limit reached; returning best-effort answer."
    elif verdict == "REJECT":
        if config.policy.reject_action == "replan":
            replans = int(iteration.get("replans") or 0) + 1
            iteration["replans"] = replans
            iteration["executor_turns"] = 0
            updates["iteration"] = iteration
            if replans > config.policy.max_review_cycles:
                from app.agent_workflow.nodes.executor import _fallback_answer

                updates["phase"] = "done"
                updates["error"] = "Reviewer rejected; replan limit reached."
                updates["final_answer"] = state.get("draft_answer") or _fallback_answer(state)
            else:
                required = review.get("required_changes") or review.get("issues") or []
                updates["review_feedback"] = "\n".join(f"- {item}" for item in required)
                updates["phase"] = "planning"
                updates["plan"] = {}
                updates["current_step_index"] = 0
                updates["artifacts"] = []
                updates["tool_calls"] = []
                updates["candidate_tools"] = []
                updates["draft_answer"] = ""
        else:
            updates["phase"] = "done"
            updates["error"] = "Reviewer rejected the answer."

    updates["events"] = [
        {
            "step": "reviewer.completed",
            "verdict": verdict,
            "issues": review.get("issues") or [],
            "missing_evidence": review.get("missing_evidence") or [],
            "required_changes": review.get("required_changes") or [],
            "draft_answer_preview": (state.get("draft_answer") or "")[:300],
            "artifact_count": len(state.get("artifacts") or []),
            "tool_call_count": len(state.get("tool_calls") or []),
        }
    ]
    return updates
