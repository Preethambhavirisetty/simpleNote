from __future__ import annotations

import json

from app.agent_workflow.config import AgentConfig
from app.agent_workflow.deadlines import DeadlineExceeded, run_with_deadline
from app.agent_workflow.prompts.output_markdown import MARKDOWN_OUTPUT_RULES
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.state import AgentState
from app.agent_workflow.telemetry import llm_call


def revision_node(state: AgentState, *, config: AgentConfig, llm: LlmProvider) -> dict[str, object]:
    """Revise the draft once using the same facts and reviewer issues."""
    # Revision is intentionally bounded and does not call tools. If the facts
    # are insufficient, it should make the limitation clear instead of looping.
    iteration = dict(state.get("iteration") or {})
    iteration["revision_cycles"] = int(iteration.get("revision_cycles") or 0) + 1
    max_cycles = max(1, int(config.policy.revision.max_cycles or 1))
    if iteration["revision_cycles"] > max_cycles:
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


def _row_evidence_snippet(state: AgentState, *, limit: int = 40) -> str:
    """Compact row-level evidence for numeric fidelity during revision."""
    lines: list[str] = []
    for artifact in state.get("artifacts") or []:
        if str(artifact.get("tool") or "") != "get_panel_data":
            continue
        raw_ref = artifact.get("raw_ref") if isinstance(artifact.get("raw_ref"), dict) else {}
        rows = raw_ref.get("rows")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict):
                lines.append(json.dumps(row, ensure_ascii=True, sort_keys=True))
            if len(lines) >= limit:
                return "\n".join(lines)
    return "\n".join(lines)


def _filter_conflict_instruction(changes: list[str]) -> str:
    joined = " ".join(changes).lower()
    if "conflicts with" not in joined and "filter" not in joined:
        return ""
    return (
        "FILTER CONFLICT: When site and lab disagree, do not claim the answer applies to the "
        "conflicting site/region in the opening sentence. Lead with the lab/site that matches "
        "the returned data, note the user's conflicting filter, and keep numeric values unchanged.\n\n"
    )


def _numeric_fidelity_instruction(changes: list[str], issues: list[str]) -> str:
    joined = " ".join(changes + issues).lower()
    if not any(token in joined for token in ("numeric", "kW", "kw", "value", "table", "correct")):
        return ""
    return (
        "NUMERIC FIDELITY: Copy every kW/capacity number exactly from the facts and row evidence "
        "snippet below. Do not round, swap, or reuse numbers from the flawed draft.\n\n"
    )


def _ordered_facts(state: AgentState) -> str:
    facts = list(state.get("facts") or [])
    panel_facts = [fact for fact in facts if str(fact.get("tool") or "") == "get_panel_data"]
    other_facts = [fact for fact in facts if str(fact.get("tool") or "") != "get_panel_data"]
    ordered = panel_facts + other_facts
    return "\n".join(f"- {fact.get('text', '')} [tool={fact.get('tool', '')}]" for fact in ordered)


def _messages(state: AgentState) -> list[dict[str, str]]:
    """Build the revision prompt from the same facts and concrete defects."""
    review = state.get("review") or {}
    issues = list(review.get("issues") or [])
    required = list(review.get("required_changes") or [])
    missing = list(review.get("missing_evidence") or [])
    changes = "\n".join(f"- {item}" for item in (required or issues))
    unverified = "\n".join(f"- {item}" for item in missing)
    row_snippet = _row_evidence_snippet(state)
    filter_instruction = _filter_conflict_instruction(required + issues)
    numeric_instruction = _numeric_fidelity_instruction(required, issues)
    return [
        {
            "role": "system",
            "content": (
                "You are the revision node. Improve the draft using only the same facts. "
                "Do not call tools, ask for hidden evidence, or add unsupported claims. "
                "Never invent values, rows, names, or numbers that are not in the facts — "
                "a fabricated answer is worse than an honest incomplete one. "
                "If evidence is missing, state the limitation plainly.\n\n"
                f"{MARKDOWN_OUTPUT_RULES}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"{filter_instruction}"
                f"{numeric_instruction}"
                f"User request:\n{state.get('user_query', '')}\n\n"
                f"Current draft:\n{state.get('draft_answer', '')}\n\n"
                f"Reviewer issues or required changes:\n{changes or '(none)'}\n\n"
                + (
                    "Evidence that could NOT be verified (the revised answer must say so "
                    "explicitly and must NOT present any of it as confirmed):\n"
                    f"{unverified}\n\n"
                    if unverified
                    else ""
                )
                + (
                    f"Row-level evidence snippet (authoritative for numeric values):\n{row_snippet}\n\n"
                    if row_snippet
                    else ""
                )
                + f"Facts:\n{_ordered_facts(state) or '(none)'}\n\n"
                "Return only the revised answer in GFM markdown."
            ),
        },
    ]


def _complete_revision(llm: LlmProvider, messages: list[dict[str, str]], max_tokens: int) -> str:
    """Run the revision LLM call inside the debug trace wrapper."""
    with llm_call(node="revision", label="revise_answer", messages=messages, max_tokens=max_tokens):
        return llm.complete(messages, max_tokens=max_tokens)
