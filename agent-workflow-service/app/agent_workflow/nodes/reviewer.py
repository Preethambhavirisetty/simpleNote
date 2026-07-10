from __future__ import annotations

import json
import re
from typing import Any

from app.agent_workflow.config import AgentConfig
from app.agent_workflow.deadlines import DeadlineExceeded, run_with_deadline
from app.agent_workflow.follow_up import follow_up_approval_gaps
from app.agent_workflow.parsing import normalize_tool_name, parse_review_markdown
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


# Only phrasings that genuinely demand live numeric/row data. Bare descriptive
# words (available, capacity, current, count) matched far too broadly and forced
# needless re-exploration, so quantitative triggers now require an actual number
# or an explicit counting question.
_LIVE_DATA_QUERY_RE = re.compile(
    r"(\bhow many\b|\bhow much\b|\bnumber of\b|"
    r"\b(?:at least|at most|no more than|under|over|below|above|less than|more than|"
    r"greater than|fewer than|exactly)\s+\d|"
    r"[<>]=?\s*\d|\d+\s*(?:kw|kv|mw|gw|gb|tb|mb|%))",
    re.I,
)
_TOOL_NAME_RE = re.compile(r"\b(?:get|list|search|run)_[a-z][a-z0-9_]*\b", re.I)


def _question_needs_live_data(query: str) -> bool:
    return bool(_LIVE_DATA_QUERY_RE.search(query or ""))


def _artifacts_have_tabular_data(state: AgentState) -> bool:
    for artifact in state.get("artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        raw_ref = artifact.get("raw_ref") if isinstance(artifact.get("raw_ref"), dict) else {}
        rows = raw_ref.get("rows")
        if isinstance(rows, list) and rows:
            return True
        row_count = raw_ref.get("row_count")
        if isinstance(row_count, int) and row_count > 0:
            return True
        items = raw_ref.get("items")
        if isinstance(items, list) and items:
            return True
    return False


def _quantitative_evidence_gaps(state: AgentState) -> list[str]:
    """Block APPROVE when the question needs live figures but no tool returned rows."""
    if not _question_needs_live_data(str(state.get("user_query") or "")):
        return []
    if _artifacts_have_tabular_data(state):
        return []
    return ["Gather live tool results with row-level data before approving a quantitative answer"]


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


def _plan_with_explore_step(state: AgentState, feedback: str, feedback_items: list[str]) -> dict[str, Any]:
    """Provide a bounded 'gather missing evidence' step for the executor to work.

    Re-exploration reuses a single trailing step (refreshing its guidance) rather
    than appending a new one each cycle, so the plan does not grow an unbounded
    run of identical "Gather missing evidence" steps across review cycles.
    """
    plan = dict(state.get("plan") or {})
    steps = list(plan.get("steps") or [])
    tools_needed = _tools_mentioned_in_feedback(feedback_items, state)
    explore_step = {
        "title": "Gather missing evidence",
        "action": feedback or "Gather the missing evidence identified in review.",
        "tool_hint": tools_needed[0] if tools_needed else "auto",
        "required_tools": tools_needed,
        "stop_condition": (
            "Each required tool returned successful results with data"
            if tools_needed
            else "Missing evidence identified in review has been gathered"
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
    elif verdict == "REVISE" and _needs_re_explore(state, review, config):
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
        required = review.get("missing_evidence") or review.get("required_changes") or review.get("issues") or []
        feedback = "\n".join(f"- {item}" for item in required)
        plan = _plan_with_explore_step(state, feedback, [str(item) for item in required])
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
