from __future__ import annotations

import json
from typing import Any

from app.agent_workflow.config import AgentConfig
from app.agent_workflow.deadlines import DeadlineExceeded, run_with_deadline
from app.agent_workflow.follow_up import follow_up_approval_gaps
from app.agent_workflow.parsing import parse_executor_action
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.state import AgentState
from app.agent_workflow.telemetry import llm_call


def _successful_tools(state: AgentState) -> set[str]:
    """Return tools that completed successfully in this workflow turn."""
    return {
        str(record.get("name") or "")
        for record in (state.get("tool_calls") or [])
        if str(record.get("status") or "") == "ok" and record.get("name")
    }


def _completion_gaps(state: AgentState) -> list[str]:
    """Run deterministic checks before accepting an APPROVE verdict."""
    gaps: list[str] = []
    query = str(state.get("user_query") or "").lower()
    successful = _successful_tools(state)
    artifacts = state.get("artifacts") or []
    artifact_tools = {str(artifact.get("tool") or "") for artifact in artifacts if artifact.get("tool")}
    draft = str(state.get("draft_answer") or "")

    card_intent = any(token in query for token in ("card", "cards", "trello"))
    if card_intent:
        if "list_boards" in successful and "get_cards" not in successful:
            gaps.append("list_boards succeeded but get_cards was never called with a board_id or board_name")
        elif "get_cards" not in successful and ("board" in query or "trello" in query):
            gaps.append("User asked about Trello cards but get_cards evidence is missing")

    for artifact in artifacts:
        if str(artifact.get("tool") or "") != "get_cards":
            continue
        raw_ref = artifact.get("raw_ref") if isinstance(artifact.get("raw_ref"), dict) else {}
        total = raw_ref.get("total")
        if isinstance(total, int) and total > 0 and any(
            phrase in draft.lower() for phrase in ("0 card", "no card", "zero card", "none found")
        ):
            gaps.append(f"get_cards returned {total} item(s) but the draft answer claims there are no cards")

    dashboard_intent = any(token in query for token in ("dashboard", "dashboards", "splunk"))
    if dashboard_intent and "list_dashboards" in successful and "list_dashboards" not in artifact_tools:
        gaps.append("list_dashboards was called but no grounded dashboard artifact is available")

    gaps.extend(follow_up_approval_gaps(state))
    return gaps


def reviewer_node(state: AgentState, *, config: AgentConfig, llm: LlmProvider) -> dict[str, Any]:
    """Judge the synthesized draft against facts without authoring a new answer."""
    # The reviewer is only a gate. It returns pass/revise/reject metadata; the
    # revision node owns any rewrite, and it gets the same facts instead of new tools.
    reviewer_cfg = config.policy.reviewer
    if not reviewer_cfg.enabled:
        return {
            "phase": "done",
            "final_answer": state.get("draft_answer") or "",
            "review": {"verdict": "SKIPPED", "reason": "reviewer_disabled"},
            "events": [{"step": "reviewer.skipped", "reason": "reviewer_disabled"}],
        }

    iteration = dict(state.get("iteration") or {})
    iteration["review_cycles"] = int(iteration.get("review_cycles") or 0) + 1

    if iteration["review_cycles"] > max(1, int(reviewer_cfg.max_cycles or 1)):
        return {
            "phase": "done",
            "final_answer": state.get("draft_answer") or "",
            "iteration": iteration,
            "review": {"verdict": "SKIPPED", "reason": "review_limit_reached"},
            "error": state.get("error") or "Review limit reached; returning best available draft.",
            "events": [{"step": "reviewer.limit_reached", "review_cycles": iteration["review_cycles"]}],
        }

    messages = _messages(state)
    try:
        raw = run_with_deadline(
            lambda: _complete_review(llm, messages, reviewer_cfg.max_tokens),
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

    review = _parse_review_json(raw)
    verdict = str(review.get("verdict") or "REVISE").upper()
    if verdict not in {"APPROVE", "REVISE", "REJECT"}:
        verdict = "REVISE"
    review["verdict"] = verdict

    completion_gaps = _completion_gaps(state) if verdict == "APPROVE" else []
    if completion_gaps:
        verdict = "REVISE"
        review["verdict"] = "REVISE"
        review["missing_evidence"] = list(dict.fromkeys((review.get("missing_evidence") or []) + completion_gaps))
        review["required_changes"] = list(dict.fromkeys((review.get("required_changes") or []) + completion_gaps))

    updates: dict[str, Any] = {"review": review, "iteration": iteration}
    if verdict == "APPROVE":
        updates["phase"] = "done"
        updates["final_answer"] = str(state.get("draft_answer") or "").strip()
        updates["error"] = None
    elif verdict == "REVISE" and int(iteration.get("revision_cycles") or 0) < 1:
        updates["phase"] = "revising"
        required = review.get("required_changes") or review.get("issues") or review.get("missing_evidence") or []
        updates["review_feedback"] = "\n".join(f"- {item}" for item in required)
    else:
        updates["phase"] = "done"
        updates["final_answer"] = str(state.get("draft_answer") or "").strip()
        if verdict == "REJECT":
            updates["error"] = state.get("error") or "Reviewer rejected the draft; returning best available answer with existing facts."

    updates["events"] = [
        {
            "step": "reviewer.completed",
            "verdict": verdict,
            "issues": review.get("issues") or [],
            "missing_evidence": review.get("missing_evidence") or [],
            "required_changes": review.get("required_changes") or [],
            "completion_gaps": completion_gaps,
            "fact_count": len(state.get("facts") or []),
            "artifact_count": len(state.get("artifacts") or []),
            "tool_call_count": len(state.get("tool_calls") or []),
            "draft_answer_preview": (state.get("draft_answer") or "")[:300],
        }
    ]
    return updates


def _messages(state: AgentState) -> list[dict[str, str]]:
    """Build a compact judge prompt from the draft and facts."""
    facts = "\n".join(f"- {fact.get('text', '')} [tool={fact.get('tool', '')}]" for fact in state.get("facts") or [])
    return [
        {
            "role": "system",
            "content": (
                "You are the reviewer node. Judge the draft against the supplied facts only. "
                "Do not rewrite the answer. Do not request more tools unless the draft cannot be made honest from these facts. "
                "Return only JSON with keys: verdict, issues, missing_evidence, required_changes. "
                "verdict must be APPROVE, REVISE, or REJECT."
            ),
        },
        {
            "role": "user",
            "content": (
                f"User request:\n{state.get('user_query', '')}\n\n"
                f"Draft answer:\n{state.get('draft_answer', '')}\n\n"
                f"Facts:\n{facts or '(none)'}\n\n"
                "Return JSON only."
            ),
        },
    ]

def _parse_review_json(text: str) -> dict[str, Any]:
    """Parse reviewer JSON and normalize list fields."""
    parsed = parse_executor_action(text)
    if not isinstance(parsed, dict):
        parsed = {}
    for key in ("issues", "missing_evidence", "required_changes"):
        value = parsed.get(key)
        if isinstance(value, str):
            parsed[key] = [value] if value.strip() else []
        elif not isinstance(value, list):
            parsed[key] = []
    parsed.pop("approved_answer", None)
    try:
        json.dumps(parsed)
    except TypeError:
        parsed = {"verdict": "REVISE", "issues": ["Reviewer returned non-JSON data"], "missing_evidence": [], "required_changes": []}
    return parsed


def _complete_review(llm: LlmProvider, messages: list[dict[str, str]], max_tokens: int) -> str:
    """Run the reviewer LLM call inside the debug trace wrapper."""
    with llm_call(node="reviewer", label="judge_draft", messages=messages, max_tokens=max_tokens):
        return llm.complete(messages, max_tokens=max_tokens)
