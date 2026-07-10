from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_FOLLOW_UP_RE = re.compile(
    r"\b("
    r"them|those|these|this|it|same|above|previous|earlier|prior|"
    r"that list|serial|table|count|how many|reformat|format|show again"
    r")\b",
    re.IGNORECASE,
)
_REFINEMENT_RE = re.compile(
    r"\b("
    r"if there is no|if not|if no\b|otherwise|instead\b|what about|"
    r"no explicit|give me all|all rows|from 0 to|same site|same dashboard|"
    r"under\s+\d|less than\s+\d|more than\s+\d|at least\s+\d|"
    r"then give|then show|then list|also show|also give|still on"
    r")\b",
    re.IGNORECASE,
)
_DATA_FOLLOW_UP_RE = re.compile(
    r"\b(table|serial|count|how many|list|show|format|reformat|filter|sort|rows)\b",
    re.IGNORECASE,
)
_SITE_RE = re.compile(r"\bsite\s*=\s*([A-Za-z0-9_-]+)", re.IGNORECASE)
_SNAKE_ID_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\b\d+\b")


@dataclass(frozen=True)
class FollowUpPolicy:
    """Resolved follow-up behavior for one workflow turn."""

    is_follow_up: bool = False
    require_tool_recall: bool = False
    required_tools: frozenset[str] = field(default_factory=frozenset)
    persisted_artifact_count: int = 0


def _history_text(history: list[dict[str, Any]], *, limit: int = 4) -> str:
    chunks: list[str] = []
    for item in history[-limit:]:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if content:
            chunks.append(content)
    return "\n".join(chunks)


def _topic_anchors(text: str) -> set[str]:
    """Distinctive tokens that tie a turn to a prior topic (numbers, ids, sites)."""
    anchors: set[str] = set()
    for match in _NUMBER_RE.finditer(text):
        anchors.add(match.group())
    for match in _SNAKE_ID_RE.finditer(text):
        anchors.add(match.group().lower())
    for match in _SITE_RE.finditer(text):
        anchors.add(match.group(1).lower())
    return anchors


def _topic_continues(query: str, history: list[dict[str, Any]]) -> bool:
    """Return whether the query shares topic anchors with recent history."""
    prior = _history_text(history)
    if not prior:
        return False
    query_anchors = _topic_anchors(query)
    history_anchors = _topic_anchors(prior)
    if not query_anchors or not history_anchors:
        return False
    overlap = query_anchors & history_anchors
    if not overlap:
        return False
    # A shared number or a shared multi-part identifier (e.g. a dashboard/board
    # name like "autopod_rows_availability") is distinctive enough on its own to
    # signal continuation; generic single-token overlaps still need a second hit.
    if any(token.isdigit() or "_" in token for token in overlap):
        return True
    return len(overlap) >= 2


def is_follow_up_query(query: str, history: list[dict[str, Any]]) -> bool:
    """Return whether the query likely refers to prior-turn assistant output."""
    if not history:
        return False
    cleaned = str(query or "").strip()
    if not cleaned:
        return False
    if _FOLLOW_UP_RE.search(cleaned):
        return True
    if _REFINEMENT_RE.search(cleaned):
        return True
    if _topic_continues(cleaned, history):
        return True
    if len(cleaned.split()) <= 20 and _DATA_FOLLOW_UP_RE.search(cleaned):
        return True
    return False


def _last_user_text(history: list[dict[str, Any]]) -> str:
    """Return the most recent prior user message content, if any."""
    for item in reversed(history):
        if isinstance(item, dict) and str(item.get("role") or "") == "user":
            content = str(item.get("content") or "").strip()
            if content:
                return content
    return ""


def build_search_query(query: str, history: list[dict[str, Any]]) -> str:
    """Deterministic standalone-query fallback used when the planner is off.

    On a follow-up turn a bare question ("how many are there?") has no nouns for
    semantic tool search, so the most recent user turn is prepended to restore
    context. First-shot queries are returned unchanged. The planner's LLM rewrite
    is preferred when available; this is the no-LLM safety net.
    """
    cleaned = str(query or "").strip()
    if not is_follow_up_query(cleaned, history):
        return cleaned
    prev = _last_user_text(history)
    if prev and prev.lower() not in cleaned.lower():
        return f"{prev} {cleaned}".strip()
    return cleaned


def evidence_tools_from_artifacts(artifacts: list[dict[str, Any]]) -> set[str]:
    """Return tool names represented by persisted artifacts."""
    tools: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        name = str(artifact.get("tool") or "").strip()
        if name:
            tools.add(name)
    return tools


def resolve_follow_up_policy(
    *,
    query: str,
    history: list[dict[str, Any]],
    persisted_artifacts: list[dict[str, Any]],
    persistence_active: bool,
    require_tool_on_follow_up: bool,
) -> FollowUpPolicy:
    """Decide whether this turn can reuse persisted artifacts or must recall tools."""
    if not is_follow_up_query(query, history):
        return FollowUpPolicy()

    persisted_count = len(persisted_artifacts)
    has_persisted_evidence = persistence_active and persisted_count > 0
    if has_persisted_evidence:
        return FollowUpPolicy(
            is_follow_up=True,
            require_tool_recall=False,
            required_tools=frozenset(),
            persisted_artifact_count=persisted_count,
        )

    if not require_tool_on_follow_up:
        return FollowUpPolicy(is_follow_up=True, persisted_artifact_count=persisted_count)

    # A follow-up with no persisted evidence must recall tools before answering.
    # Which tools is left generic: the executor selects them via semantic tool
    # search, and follow_up_tool_recall_missing enforces that some fresh tool
    # call happens (no app-specific tool-name heuristics).
    return FollowUpPolicy(
        is_follow_up=True,
        require_tool_recall=True,
        required_tools=frozenset(),
        persisted_artifact_count=persisted_count,
    )


def apply_follow_up_runtime_context(
    runtime_context: dict[str, Any],
    policy: FollowUpPolicy,
) -> dict[str, Any]:
    """Merge follow-up flags into runtime_context for downstream nodes."""
    merged = dict(runtime_context)
    if not policy.is_follow_up:
        return merged
    merged["follow_up"] = True
    if policy.persisted_artifact_count:
        merged["persisted_artifact_count"] = policy.persisted_artifact_count
    if policy.require_tool_recall:
        merged["require_tools"] = True
        if policy.required_tools:
            merged["follow_up_required_tools"] = sorted(policy.required_tools)
    return merged


def _successful_tools(state: dict[str, Any]) -> set[str]:
    return {
        str(record.get("name") or "")
        for record in (state.get("tool_calls") or [])
        if str(record.get("status") or "") == "ok" and record.get("name")
    }


def follow_up_tool_recall_missing(state: dict[str, Any]) -> list[str]:
    """Return missing evidence tools blocking finish/draft on follow-up turns."""
    runtime = state.get("runtime_context") if isinstance(state.get("runtime_context"), dict) else {}
    if not runtime.get("follow_up"):
        return []

    artifacts = state.get("artifacts") or []
    artifact_tools = evidence_tools_from_artifacts(artifacts)
    successful = _successful_tools(state)
    required = {str(item).strip() for item in (runtime.get("follow_up_required_tools") or []) if str(item).strip()}

    if required:
        missing = sorted(required - successful)
        if missing and required <= artifact_tools:
            return []
        if missing:
            return [f"Follow-up requires tool evidence: {', '.join(missing)}"]
        return []

    if runtime.get("require_tools") and not successful:
        if artifacts and int(runtime.get("persisted_artifact_count") or 0) > 0:
            return []
        return ["Follow-up requires a fresh tool call before answering"]

    return []


def follow_up_approval_gaps(state: dict[str, Any]) -> list[str]:
    """Deterministic reviewer checks for follow-up grounding."""
    runtime = state.get("runtime_context") if isinstance(state.get("runtime_context"), dict) else {}
    if not runtime.get("follow_up"):
        return []

    gaps = follow_up_tool_recall_missing(state)
    if gaps:
        return gaps

    artifacts = state.get("artifacts") or []
    if runtime.get("require_tools") and not artifacts and not _successful_tools(state):
        return ["Follow-up answer lacks tool-backed evidence"]

    return []
