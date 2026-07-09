from __future__ import annotations

import json
import re
from typing import Any

from app.agent_workflow.config import AgentConfig
from app.agent_workflow.deadlines import DeadlineExceeded, run_with_deadline
from app.agent_workflow.follow_up import follow_up_approval_gaps
from app.agent_workflow.parsing import parse_review_markdown
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.state import AgentState
from app.agent_workflow.telemetry import llm_call


_VERDICTS = {"APPROVE", "REVISE", "REJECT"}
_REVIEW_LIST_KEYS = ("issues", "missing_evidence", "required_changes")


def _successful_tools(state: AgentState) -> set[str]:
    """Return tools that completed successfully in this workflow turn."""
    return {
        str(record.get("name") or "")
        for record in (state.get("tool_calls") or [])
        if str(record.get("status") or "") == "ok" and record.get("name")
    }


def _formatting_gaps(draft: str) -> list[str]:
    """Flag user-facing answers that lack basic markdown structure."""
    text = (draft or "").strip()
    if len(text) < 200:
        return []
    has_heading = "##" in text
    has_list = "\n- " in text or "\n* " in text or text.lstrip().startswith(("- ", "* "))
    has_table = "|" in text and "\n|" in text
    if has_heading or has_list or has_table:
        return []
    return ["Format the answer as GFM markdown with a ## heading and bullet lists or tables"]


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
    # NOTE: formatting gaps are handled separately in reviewer_node — they are a
    # wording fix (text-revise), not missing evidence, so they must not land in
    # missing_evidence or they would wrongly trigger re-exploration.
    return gaps


def _needs_re_explore(state: AgentState, review: dict[str, Any], config: AgentConfig) -> bool:
    """Return whether a REVISE should re-enter the executor to gather evidence.

    Evidence-revise (as opposed to text-revise) fires when the reviewer reports
    missing evidence, the run still has tools it can call, and the bounded
    re-exploration budget is not exhausted. A missing_evidence list is the
    reviewer literally saying "evidence is absent" — which a text rewrite from
    the same facts cannot fix.
    """
    if int(config.policy.max_explore_cycles) <= 0:
        return False
    iteration = state.get("iteration") or {}
    if int(iteration.get("explore_cycles") or 0) >= int(config.policy.max_explore_cycles):
        return False
    missing = [str(item).strip() for item in (review.get("missing_evidence") or []) if str(item).strip()]
    if not missing:
        return False
    # Re-exploration is only useful if the agent actually has tools to call.
    return bool(state.get("tool_calls") or state.get("candidate_tools"))


def _plan_with_explore_step(state: AgentState, feedback: str) -> dict[str, Any]:
    """Append a bounded 'gather missing evidence' step for the executor to work."""
    plan = dict(state.get("plan") or {})
    steps = list(plan.get("steps") or [])
    steps.append(
        {
            "title": "Gather missing evidence",
            "action": feedback or "Gather the missing evidence identified in review.",
            "tool_hint": "auto",
        }
    )
    plan["steps"] = steps
    return plan


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

    # An enabled reviewer always runs at least once; the schema enforces
    # max_cycles >= 1, and the floor here is a defensive guard. Disable review
    # entirely via reviewer.enabled / enable_reviewer, not max_cycles = 0.
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

    review, parse_failed = _parse_review(raw)
    verdict = str(review.get("verdict") or "REVISE").upper()
    if verdict not in {"APPROVE", "REVISE", "REJECT"}:
        verdict = "REVISE"
    review["verdict"] = verdict

    completion_gaps = _completion_gaps(state) if verdict == "APPROVE" else []
    # Formatting gaps are wording fixes, not missing evidence: they go only to
    # required_changes so they route to text-revision, never to re-exploration.
    formatting_gaps = _formatting_gaps(str(state.get("draft_answer") or "")) if verdict == "APPROVE" else []
    if completion_gaps:
        verdict = "REVISE"
        review["verdict"] = "REVISE"
        review["missing_evidence"] = list(dict.fromkeys((review.get("missing_evidence") or []) + completion_gaps))
        review["required_changes"] = list(dict.fromkeys((review.get("required_changes") or []) + completion_gaps))
    if formatting_gaps:
        verdict = "REVISE"
        review["verdict"] = "REVISE"
        review["required_changes"] = list(dict.fromkeys((review.get("required_changes") or []) + formatting_gaps))

    updates: dict[str, Any] = {"review": review, "iteration": iteration}
    re_explored = False
    if verdict == "APPROVE":
        updates["phase"] = "done"
        updates["final_answer"] = str(state.get("draft_answer") or "").strip()
        updates["error"] = None
    elif verdict == "REVISE" and _needs_re_explore(state, review, config):
        # Evidence-revise: the gap is missing tool evidence, not wording. Rewriting
        # from the same facts cannot fix that, so re-enter the executor to gather
        # more. Bounded by explore_cycles; the guidance is passed as feedback and a
        # fresh "gather missing evidence" plan step gives the executor real work.
        re_explored = True
        iteration["explore_cycles"] = int(iteration.get("explore_cycles") or 0) + 1
        required = review.get("missing_evidence") or review.get("required_changes") or review.get("issues") or []
        feedback = "\n".join(f"- {item}" for item in required)
        plan = _plan_with_explore_step(state, feedback)
        updates["iteration"] = iteration
        updates["review_feedback"] = feedback
        updates["plan"] = plan
        updates["current_step_index"] = max(0, len(plan.get("steps") or []) - 1)
        updates["candidate_tools"] = []
        updates["phase"] = "executing"
    elif verdict == "REVISE" and int(iteration.get("revision_cycles") or 0) < config.policy.revision.max_cycles:
        updates["phase"] = "revising"
        required = review.get("required_changes") or review.get("issues") or review.get("missing_evidence") or []
        updates["review_feedback"] = "\n".join(f"- {item}" for item in required)
    else:
        updates["phase"] = "done"
        updates["final_answer"] = str(state.get("draft_answer") or "").strip()
        if verdict == "REJECT":
            updates["error"] = state.get("error") or "Reviewer rejected the draft; returning best available answer with existing facts."

    events: list[dict[str, Any]] = []
    if parse_failed:
        events.append({"step": "reviewer.parse_failed", "raw_preview": (raw or "")[:300]})
    if re_explored:
        events.append(
            {
                "step": "reviewer.re_explore",
                "explore_cycles": int(iteration.get("explore_cycles") or 0),
                "missing_evidence": review.get("missing_evidence") or [],
            }
        )
    events.append(
        {
            "step": "reviewer.completed",
            "verdict": verdict,
            "re_explore": re_explored,
            "issues": review.get("issues") or [],
            "missing_evidence": review.get("missing_evidence") or [],
            "required_changes": review.get("required_changes") or [],
            "completion_gaps": completion_gaps,
            "fact_count": len(state.get("facts") or []),
            "artifact_count": len(state.get("artifacts") or []),
            "tool_call_count": len(state.get("tool_calls") or []),
            "draft_answer_preview": (state.get("draft_answer") or "")[:300],
        }
    )
    updates["events"] = events
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

def _parse_review(text: str) -> tuple[dict[str, Any], bool]:
    """Parse a reviewer response, trying JSON then markdown before a safe fallback.

    Returns the normalized review and whether parsing fell through to the safe
    REVISE default (so the caller can emit a ``reviewer.parse_failed`` event).
    """
    data = _try_json_object(text)
    if isinstance(data, dict) and _has_review_signal(data):
        return _normalize_review_fields(data), False

    if "###" in (text or ""):
        return _normalize_review_fields(dict(parse_review_markdown(text))), False

    return (
        {
            "verdict": "REVISE",
            "issues": ["Reviewer output was not valid JSON or markdown"],
            "missing_evidence": [],
            "required_changes": [],
        },
        True,
    )


def _try_json_object(text: str) -> dict[str, Any] | None:
    """Return a JSON object from the text, or None when it is not JSON."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return None


def _has_review_signal(data: dict[str, Any]) -> bool:
    """Return whether a parsed object actually looks like a reviewer verdict."""
    if str(data.get("verdict") or "").upper() in _VERDICTS:
        return True
    return any(key in data for key in (*_REVIEW_LIST_KEYS, "scorecard"))


def _normalize_review_fields(parsed: dict[str, Any]) -> dict[str, Any]:
    """Coerce reviewer list fields and guarantee a JSON-serializable result."""
    for key in _REVIEW_LIST_KEYS:
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
