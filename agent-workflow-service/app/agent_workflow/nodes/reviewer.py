from __future__ import annotations

import json
import re
from typing import Any

from app.agent_workflow.config import AgentConfig
from app.agent_workflow.deadlines import DeadlineExceeded, run_with_deadline
from app.agent_workflow.evidence_grade import (
    artifacts_have_row_level_data,
    artifacts_have_usable_row_data,
    discovery_answer_gaps,
    draft_claim_consistency_gaps,
    filter_conflict_gaps,
    question_needs_live_data as _question_needs_live_data,
    question_requires_row_evidence,
    row_evidence_gaps,
)
from app.agent_workflow.follow_up import follow_up_approval_gaps
from app.agent_workflow.parsing import extract_json_object, normalize_tool_name, parse_review_markdown
from app.agent_workflow.providers.llm import LlmProvider
from app.agent_workflow.state import AgentState
from app.agent_workflow.telemetry import llm_call


_VERDICTS = {"APPROVE", "REVISE", "REJECT"}
_REVIEW_LIST_KEYS = ("issues", "missing_evidence", "required_changes")


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


_EMPTY_CLAIM_PHRASES = (
    "no results",
    "no items",
    "no records",
    "no matches",
    "no data",
    "no entries",
    "none found",
    "nothing found",
    "returned nothing",
    "not find any",
    "couldn't find any",
    "could not find any",
    "empty result",
)

_TOOL_NAME_RE = re.compile(r"\b(?:get|list|search|run)_[a-z][a-z0-9_]*\b", re.I)


def _artifacts_have_tabular_data(state: AgentState) -> bool:
    return artifacts_have_row_level_data(state.get("artifacts") or [])


def _quantitative_evidence_gaps(state: AgentState) -> list[str]:
    """Block APPROVE when numeric questions lack row-level tool results."""
    return row_evidence_gaps(
        str(state.get("user_query") or ""),
        state.get("artifacts") or [],
        plan=state.get("plan") if isinstance(state.get("plan"), dict) else None,
    )


def _tools_mentioned_in_feedback(items: list[str], state: AgentState) -> list[str]:
    """Infer concrete tool names from reviewer missing-evidence notes."""
    known = {
        normalize_tool_name(record.get("name"))
        for record in (state.get("tool_calls") or [])
        if record.get("name")
    }
    for candidate in state.get("candidate_tools") or []:
        if candidate.get("name"):
            known.add(normalize_tool_name(candidate.get("name")))
    found: list[str] = []
    for item in items:
        for match in _TOOL_NAME_RE.finditer(str(item or "")):
            name = normalize_tool_name(match.group(0))
            if name and (name in known or name.startswith(("get_", "list_", "search_", "run_"))):
                found.append(name)
    return list(dict.fromkeys(found))


def _completion_gaps(state: AgentState) -> list[str]:
    """Generic deterministic EVIDENCE gaps (missing tool data) before an APPROVE.

    App-agnostic: it surfaces only follow-up recall gaps — evidence the turn
    needs but has not gathered. These go to missing_evidence and can trigger a
    bounded re-exploration. All app-specific tool heuristics were removed;
    completeness is otherwise the reviewer LLM's judgment.
    """
    gaps = list(follow_up_approval_gaps(state))
    gaps.extend(_quantitative_evidence_gaps(state))
    return list(dict.fromkeys(gaps))


def _contradiction_gaps(state: AgentState) -> list[str]:
    """Flag a draft that claims nothing was found while a tool actually returned data.

    Generic: it does not name any tool. This is a synthesis error — the evidence
    exists — so it is a text-revise (rewrite), not missing evidence.
    """
    draft = str(state.get("draft_answer") or "").lower()
    if not any(phrase in draft for phrase in _EMPTY_CLAIM_PHRASES):
        return []
    for artifact in state.get("artifacts") or []:
        raw_ref = artifact.get("raw_ref") if isinstance(artifact.get("raw_ref"), dict) else {}
        total = raw_ref.get("total")
        has_data = (
            (isinstance(total, int) and total > 0)
            or bool(raw_ref.get("items"))
            or bool(raw_ref.get("facts"))
            or bool(raw_ref.get("rows"))
        )
        if has_data:
            return [f"{artifact.get('tool', 'a tool')} returned results, but the draft says nothing was found — use that evidence"]
    return []


def _synthesis_gaps(state: AgentState) -> list[str]:
    """Deterministic REWRITE-fixable gaps: fixable from existing facts, not new tools."""
    gaps = _contradiction_gaps(state)
    gaps.extend(_formatting_gaps(str(state.get("draft_answer") or "")))
    gaps.extend(
        draft_claim_consistency_gaps(
            str(state.get("user_query") or ""),
            str(state.get("draft_answer") or ""),
            state.get("artifacts") or [],
        )
    )
    gaps.extend(
        discovery_answer_gaps(
            str(state.get("user_query") or ""),
            str(state.get("draft_answer") or ""),
            state.get("artifacts") or [],
        )
    )
    gaps.extend(
        filter_conflict_gaps(
            state.get("artifacts") or [],
            user_query=str(state.get("user_query") or ""),
        )
    )
    return gaps


def _missing_evidence_items(review: dict[str, Any]) -> list[str]:
    """Return reviewer evidence gaps as normalized strings."""
    return [str(item).strip() for item in (review.get("missing_evidence") or []) if str(item).strip()]


def _unresolved_evidence_blocks_completion(state: AgentState, review: dict[str, Any]) -> bool:
    """Whether reviewer missing_evidence should end the run as incomplete."""
    missing = _missing_evidence_items(review)
    if not missing:
        return False
    if artifacts_have_usable_row_data(state.get("artifacts") or []):
        if not _completion_gaps(state):
            return False
    return True


def _incomplete_evidence_updates(
    state: AgentState,
    *,
    review: dict[str, Any],
    iteration: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    """Return a terminal, honest result for unresolved evidence gaps."""
    missing = _missing_evidence_items(review)
    missing_text = "\n".join(f"- {item}" for item in missing) if missing else "- Required evidence was not gathered."
    answer = (
        "I could not complete this request with reliable evidence.\n\n"
        f"Missing evidence:\n{missing_text}\n\n"
        "I am not going to infer or fabricate the final answer from incomplete tool results."
    )
    return {
        "phase": "done",
        "draft_answer": answer,
        "draft_kind": "mechanical",
        "final_answer": answer,
        "iteration": iteration,
        "error": state.get("error") or f"Incomplete evidence: {reason}",
        "review": review,
    }


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
    plan = state.get("plan") if isinstance(state.get("plan"), dict) else {}
    if str(plan.get("evidence_required") or "") == "catalog":
        return False
    iteration = state.get("iteration") or {}
    if int(iteration.get("explore_cycles") or 0) >= int(config.policy.max_explore_cycles):
        return False
    missing = _missing_evidence_items(review)
    if not missing:
        return False
    if artifacts_have_usable_row_data(state.get("artifacts") or []):
        if not _completion_gaps(state):
            return False
    # Re-exploration is only useful when the run is tool-capable. Persisted
    # artifacts count too: a follow-up that reused session evidence (and thus
    # made no tool calls yet) must still be able to go gather what's missing.
    return bool(state.get("tool_calls") or state.get("candidate_tools") or state.get("artifacts"))


def _needs_row_level_gather(state: AgentState, feedback_items: list[str]) -> bool:
    """Whether re-exploration must return row-level tool results, not catalogs."""
    if _artifacts_have_tabular_data(state):
        return False
    if _question_needs_live_data(str(state.get("user_query") or "")):
        return True
    if question_requires_row_evidence(
        str(state.get("user_query") or ""),
        state.get("plan") if isinstance(state.get("plan"), dict) else None,
    ):
        return True
    return any("row-level" in str(item).lower() for item in feedback_items)


def _plan_with_explore_step(state: AgentState, feedback_items: list[str]) -> dict[str, Any]:
    """Provide a bounded 'gather missing evidence' step for the executor to work.

    Re-exploration reuses a single trailing step (refreshing its guidance) rather
    than appending a new one each cycle, so the plan does not grow an unbounded
    run of identical "Gather missing evidence" steps across review cycles.
    """
    plan = dict(state.get("plan") or {})
    steps = list(plan.get("steps") or [])
    tools_needed = _tools_mentioned_in_feedback(feedback_items, state)
    # The step action stays short: it is concatenated into the semantic
    # tool-search query, and the full feedback bullets already reach the model
    # through review_feedback (dumping them here polluted tool discovery).
    require_row_level = _needs_row_level_gather(state, feedback_items)
    explore_step = {
        "title": "Gather missing evidence",
        "action": "Gather the missing evidence identified in review (see reviewer feedback).",
        "tool_hint": tools_needed[0] if tools_needed else "auto",
        "required_tools": tools_needed,
        "require_row_level": require_row_level,
        "stop_condition": (
            "Row-level tool results have been returned for this step"
            if require_row_level
            else (
                "Each required tool returned successful results with data"
                if tools_needed
                else "Missing evidence identified in review has been gathered"
            )
        ),
        "origin": "re_explore",
    }
    if steps and steps[-1].get("origin") == "re_explore":
        steps[-1] = explore_step
    else:
        steps.append(explore_step)
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

    # Evidence gaps (missing tool data) can trigger bounded re-exploration, so
    # they land in missing_evidence. Synthesis gaps (contradiction, formatting)
    # are fixable from existing facts, so they go only to required_changes and
    # route to text-revision — never to re-exploration.
    completion_gaps = _completion_gaps(state) if verdict == "APPROVE" else []
    synthesis_gaps = _synthesis_gaps(state) if verdict == "APPROVE" else []
    if completion_gaps:
        verdict = "REVISE"
        review["verdict"] = "REVISE"
        review["missing_evidence"] = list(dict.fromkeys((review.get("missing_evidence") or []) + completion_gaps))
        review["required_changes"] = list(dict.fromkeys((review.get("required_changes") or []) + completion_gaps))
    if synthesis_gaps:
        verdict = "REVISE"
        review["verdict"] = "REVISE"
        review["required_changes"] = list(dict.fromkeys((review.get("required_changes") or []) + synthesis_gaps))

    updates: dict[str, Any] = {"review": review, "iteration": iteration}
    re_explored = False
    if verdict == "APPROVE":
        updates["phase"] = "done"
        updates["final_answer"] = str(state.get("draft_answer") or "").strip()
        updates["error"] = None
    elif verdict in {"REVISE", "REJECT"} and _needs_re_explore(state, review, config):
        # REJECT with missing evidence gets the same bounded re-exploration as
        # REVISE: returning the rejected draft when tools were never exercised
        # (e.g. the whole run produced no successful call) just ships a bad answer.
        # Evidence-revise: the gap is missing tool evidence, not wording. Rewriting
        # from the same facts cannot fix that, so re-enter the executor to gather
        # more. Bounded by explore_cycles; the guidance is passed as feedback and a
        # fresh "gather missing evidence" plan step gives the executor real work.
        re_explored = True
        iteration["explore_cycles"] = int(iteration.get("explore_cycles") or 0) + 1
        iteration["no_progress_turns"] = 0
        # Give the re-entered executor a fresh iteration budget; otherwise a
        # re-explore triggered near max_executor_iterations bails immediately and
        # gathers nothing. Total turns stay bounded by max_explore_cycles.
        iteration["executor_turns"] = 0
        # Allow one more reviewer pass after gathering; otherwise max_review_cycles
        # is consumed by the pre-gather draft and the bad answer ships unchecked.
        iteration["review_cycles"] = 0
        required = review.get("missing_evidence") or review.get("required_changes") or review.get("issues") or []
        feedback = "\n".join(f"- {item}" for item in required)
        plan = _plan_with_explore_step(state, [str(item) for item in required])
        updates["iteration"] = iteration
        updates["review_feedback"] = feedback
        updates["plan"] = plan
        updates["current_step_index"] = max(0, len(plan.get("steps") or []) - 1)
        updates["candidate_tools"] = []
        updates["phase"] = "executing"
    elif verdict in {"REVISE", "REJECT"} and _unresolved_evidence_blocks_completion(state, review):
        updates.update(
            _incomplete_evidence_updates(
                state,
                review=review,
                iteration=iteration,
                reason="reviewer evidence gaps remained unresolved",
            )
        )
    elif verdict in {"REVISE", "REJECT"} and _missing_evidence_items(review) and artifacts_have_usable_row_data(
        state.get("artifacts") or []
    ):
        updates["phase"] = "revising"
        required = review.get("required_changes") or review.get("missing_evidence") or review.get("issues") or []
        updates["review_feedback"] = "\n".join(f"- {item}" for item in required)
    elif verdict == "REVISE" and int(iteration.get("revision_cycles") or 0) < config.policy.revision.max_cycles:
        updates["phase"] = "revising"
        required = review.get("required_changes") or review.get("issues") or []
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
    elif str(updates.get("error") or "").startswith("Incomplete evidence:"):
        events.append(
            {
                "step": "reviewer.incomplete_evidence",
                "explore_cycles": int(iteration.get("explore_cycles") or 0),
                "missing_evidence": review.get("missing_evidence") or [],
                "message": updates.get("error"),
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
    data = extract_json_object(text, prefer_key="verdict")
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
