from __future__ import annotations

from app.agent_workflow.config import AgentConfig
from app.agent_workflow.deadlines import DeadlineExceeded, run_with_deadline
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.state import AgentState
from app.agent_workflow.telemetry import llm_call


def revision_node(state: AgentState, *, config: AgentConfig, llm: LlmProvider) -> dict[str, object]:
    """Revise the draft once using the same facts and reviewer issues."""
    # Revision is intentionally bounded and does not call tools. If the facts
    # are insufficient, it should make the limitation clear instead of looping.
    iteration = dict(state.get("iteration") or {})
    iteration["revision_cycles"] = int(iteration.get("revision_cycles") or 0) + 1
    if iteration["revision_cycles"] > 1:
        return {
            "phase": "done",
            "final_answer": state.get("draft_answer") or "",
            "iteration": iteration,
            "error": state.get("error") or "Revision limit reached; returning best available draft.",
            "events": [{"step": "revision.limit_reached", "revision_cycles": iteration["revision_cycles"]}],
        }

    messages = _messages(state)
    try:
        revised = run_with_deadline(
            lambda: _complete_revision(llm, messages, config.policy.executor.synthesize_max_tokens),
            timeout_seconds=config.policy.llm_timeout_seconds,
            label="revision LLM call",
        ).strip()
    except DeadlineExceeded as exc:
        return {
            "phase": "done",
            "final_answer": state.get("draft_answer") or "",
            "iteration": iteration,
            "error": str(exc),
            "events": [{"step": "revision.timeout", "error": str(exc)}],
        }

    final_answer = revised or str(state.get("draft_answer") or "")
    return {
        "phase": "done",
        "draft_answer": final_answer,
        "draft_kind": "llm",
        "final_answer": final_answer,
        "iteration": iteration,
        "events": [{"step": "revision.completed", "answer_chars": len(final_answer), "revision_cycles": iteration["revision_cycles"]}],
    }


def _messages(state: AgentState) -> list[dict[str, str]]:
    """Build the revision prompt from the same facts and concrete defects."""
    review = state.get("review") or {}
    issues = list(review.get("issues") or [])
    required = list(review.get("required_changes") or [])
    missing = list(review.get("missing_evidence") or [])
    facts = "\n".join(f"- {fact.get('text', '')} [tool={fact.get('tool', '')}]" for fact in state.get("facts") or [])
    changes = "\n".join(f"- {item}" for item in (required or issues or missing))
    return [
        {
            "role": "system",
            "content": (
                "You are the revision node. Improve the draft using only the same facts. "
                "Do not call tools, ask for hidden evidence, or add unsupported claims. "
                "If evidence is missing, state the limitation plainly."
            ),
        },
        {
            "role": "user",
            "content": (
                f"User request:\n{state.get('user_query', '')}\n\n"
                f"Current draft:\n{state.get('draft_answer', '')}\n\n"
                f"Reviewer issues or required changes:\n{changes or '(none)'}\n\n"
                f"Facts:\n{facts or '(none)'}\n\n"
                "Return only the revised answer text."
            ),
        },
    ]


def _complete_revision(llm: LlmProvider, messages: list[dict[str, str]], max_tokens: int) -> str:
    """Run the revision LLM call inside the debug trace wrapper."""
    with llm_call(node="revision", label="revise_answer", messages=messages, max_tokens=max_tokens):
        return llm.complete(messages, max_tokens=max_tokens)
