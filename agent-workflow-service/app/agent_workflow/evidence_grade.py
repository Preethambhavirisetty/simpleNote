from __future__ import annotations

import re
from typing import Any

# Keys the truncator may preserve for query-result payloads (see truncator.py).
_ROW_LEVEL_KEYS = ("rows", "results")

_LIVE_DATA_QUERY_RE = re.compile(
    r"(\bhow many\b|\bhow much\b|\bnumber of\b|"
    r"\b(?:at least|at most|no more than|under|over|below|above|less than|more than|"
    r"greater than|fewer than|exactly)\s+\d|"
    r"[<>]=?\s*\d|\d+\s*(?:kw|kv|mw|gw|gb|tb|mb|%))",
    re.I,
)

_EXISTENCE_CLAIM_RE = re.compile(
    r"\b("
    r"is there|are there|do we have|can we|could we|does .+ have|"
    r"enough power|enough capacity|sufficient|available to host|qualifies?"
    r")\b",
    re.I,
)

_LISTING_CLAIM_RE = re.compile(
    r"\b("
    r"which rows?|what rows?|list (?:them|the|all|those|these)|"
    r"show (?:me )?(?:the )?rows?|pull live panel data|tell me if any row"
    r")\b",
    re.I,
)

_SCALAR_CLAIM_RE = re.compile(
    r"\bwhat is the\b.*\b(?:for row|in lab|at 80%)\b",
    re.I,
)

_DISCOVERY_CLAIM_RE = re.compile(
    r"\b("
    r"what dashboards|which dashboards|list dashboards|dashboards do we have|"
    r"what panels|which panels|search panels"
    r")\b",
    re.I,
)

_THRESHOLD_RE = re.compile(
    r"\b(?:at least|at most|under|over|below|above|less than|more than|greater than|"
    r"fewer than|exactly)\s+(\d+(?:\.\d+)?)\s*(?:kw|kv|mw|gw)?\b",
    re.I,
)

_TABLE_NUMBER_RE = re.compile(r"\b(\d+(?:\.\d+)?)\b")
_NA_CELL_RE = re.compile(r"\b(n/?a|null|none|-)\b", re.I)


def claim_class_from_query(query: str) -> str:
    """Classify the user question by the evidence it needs."""
    text = str(query or "").strip()
    if not text:
        return "none"
    if _DISCOVERY_CLAIM_RE.search(text):
        return "discovery"
    if _SCALAR_CLAIM_RE.search(text):
        return "scalar"
    if _LISTING_CLAIM_RE.search(text):
        return "listing"
    if _LIVE_DATA_QUERY_RE.search(text) or _EXISTENCE_CLAIM_RE.search(text):
        if _THRESHOLD_RE.search(text) or _LIVE_DATA_QUERY_RE.search(text):
            return "threshold"
        return "existence"
    if _EXISTENCE_CLAIM_RE.search(text):
        return "existence"
    return "none"


def question_needs_live_data(query: str) -> bool:
    """Backward-compatible quantitative gate."""
    return claim_class_from_query(query) in {"existence", "listing", "scalar", "threshold"}


def plan_requires_row_evidence(plan: dict[str, Any] | None) -> bool:
    """Return whether the structured plan explicitly requires row-level evidence."""
    if not isinstance(plan, dict):
        return False
    required = str(plan.get("evidence_required") or "").strip().lower()
    if required in {"row", "row_level", "rows"}:
        return True
    for step in plan.get("steps") or []:
        if not isinstance(step, dict):
            continue
        if step.get("require_row_level"):
            return True
        stop = str(step.get("stop_condition") or "").lower()
        if "row-level" in stop or "row level" in stop:
            return True
    return False


def question_requires_row_evidence(
    query: str,
    plan: dict[str, Any] | None = None,
) -> bool:
    """Return whether the turn needs row-shaped tool evidence before answering."""
    if plan_requires_row_evidence(plan):
        return True
    return question_needs_live_data(query)


def _rows_from_raw_ref(raw_ref: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in _ROW_LEVEL_KEYS:
        value = raw_ref.get(key)
        if isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, dict))
    data = raw_ref.get("data")
    if isinstance(data, dict):
        for key in _ROW_LEVEL_KEYS:
            value = data.get(key)
            if isinstance(value, list):
                rows.extend(item for item in value if isinstance(item, dict))
    return rows


def artifact_has_row_level_data(artifact: dict[str, Any]) -> bool:
    """Return whether an artifact's compact raw_ref carries query/panel rows."""
    raw_ref = artifact.get("raw_ref") if isinstance(artifact.get("raw_ref"), dict) else {}
    if raw_ref.get("ok") is False:
        return False
    for key in _ROW_LEVEL_KEYS:
        value = raw_ref.get(key)
        if isinstance(value, list) and value:
            return True
    row_count = raw_ref.get("row_count")
    if isinstance(row_count, int) and row_count > 0:
        return True
    data = raw_ref.get("data")
    if isinstance(data, dict):
        for key in _ROW_LEVEL_KEYS:
            value = data.get(key)
            if isinstance(value, list) and value:
                return True
    return False


def artifact_rows_usable(artifact: dict[str, Any]) -> bool:
    """Return whether row evidence contains at least one usable numeric measure."""
    raw_ref = artifact.get("raw_ref") if isinstance(artifact.get("raw_ref"), dict) else {}
    if raw_ref.get("ok") is False:
        return False
    if raw_ref.get("rows_usable") is True:
        return True
    if raw_ref.get("rows_usable") is False:
        return False
    rows = _rows_from_raw_ref(raw_ref)
    if not rows and isinstance(raw_ref.get("rows"), list):
        rows = [row for row in raw_ref["rows"] if isinstance(row, dict)]
    if not rows:
        return False
    from app.agent_workflow.evidence_grade_rows import rows_are_usable

    return rows_are_usable(rows)


def artifacts_have_row_level_data(artifacts: list[dict[str, Any]]) -> bool:
    return any(artifact_has_row_level_data(artifact) for artifact in artifacts if isinstance(artifact, dict))


def artifacts_have_usable_row_data(artifacts: list[dict[str, Any]]) -> bool:
    return any(artifact_rows_usable(artifact) for artifact in artifacts if isinstance(artifact, dict))


def persisted_evidence_is_metadata_only(artifacts: list[dict[str, Any]]) -> bool:
    """True when the session has artifacts but none are row-level answer evidence."""
    return bool(artifacts) and not artifacts_have_row_level_data(artifacts)


def step_has_row_level_evidence(
    artifacts: list[dict[str, Any]],
    *,
    step_index: int,
    replan_id: int = 0,
) -> bool:
    """Return whether a plan step produced at least one row-level artifact."""
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        if int(artifact.get("step_index", -1)) != step_index:
            continue
        if int(artifact.get("replan_id") or 0) != replan_id:
            continue
        if artifact_has_row_level_data(artifact):
            return True
    return False


def quantitative_evidence_gaps(
    user_query: str,
    artifacts: list[dict[str, Any]],
    *,
    plan: dict[str, Any] | None = None,
) -> list[str]:
    """Gaps when a data claim lacks row-level tool results."""
    return row_evidence_gaps(user_query, artifacts, plan=plan)


def row_evidence_gaps(
    user_query: str,
    artifacts: list[dict[str, Any]],
    *,
    plan: dict[str, Any] | None = None,
) -> list[str]:
    """Gaps when a row-backed claim lacks adequate tool evidence."""
    if not question_requires_row_evidence(user_query, plan):
        return []
    if not artifacts_have_row_level_data(artifacts):
        return [
            "Row-level tool results are required before approving this answer — "
            "metadata and catalogs are not sufficient"
        ]
    if not artifacts_have_usable_row_data(artifacts):
        return ["Row-level results were returned but contain no usable numeric values"]
    return []


def filter_conflict_gaps(
    artifacts: list[dict[str, Any]],
    *,
    user_query: str = "",
) -> list[str]:
    """Surface MCP-reported and query-derived filter conflicts as review gaps."""
    from app.agent_workflow.query_filter_conflicts import query_filter_conflict_gaps

    gaps: list[str] = []
    for artifact in artifacts:
        raw_ref = artifact.get("raw_ref") if isinstance(artifact.get("raw_ref"), dict) else {}
        conflicts = raw_ref.get("filter_conflicts")
        if isinstance(conflicts, list):
            gaps.extend(str(item).strip() for item in conflicts if str(item).strip())
    gaps.extend(query_filter_conflict_gaps(user_query))
    return list(dict.fromkeys(gaps))


def _threshold_from_query(query: str) -> tuple[str, float] | None:
    match = _THRESHOLD_RE.search(query or "")
    if not match:
        return None
    value = float(match.group(1))
    op = match.group(0).lower()
    if "less than" in op or "under" in op or "below" in op or "fewer than" in op:
        return ("lt", value)
    if "more than" in op or "over" in op or "above" in op or "at least" in op or "greater than" in op:
        return ("gt", value)
    return ("gt", value)


def _numbers_in_draft_table(draft: str) -> list[float]:
    numbers: list[float] = []
    for line in str(draft or "").splitlines():
        if "|" not in line:
            continue
        for cell in line.split("|"):
            cell = cell.strip()
            if _NA_CELL_RE.fullmatch(cell):
                continue
            match = _TABLE_NUMBER_RE.search(cell)
            if match:
                numbers.append(float(match.group(1)))
    return numbers


def _usable_numbers_from_artifacts(artifacts: list[dict[str, Any]]) -> list[float]:
    from app.agent_workflow.evidence_grade_rows import row_has_usable_measure, _parse_numeric

    values: list[float] = []
    for artifact in artifacts:
        raw_ref = artifact.get("raw_ref") if isinstance(artifact.get("raw_ref"), dict) else {}
        for row in _rows_from_raw_ref(raw_ref):
            if not isinstance(row, dict):
                continue
            for key, cell in row.items():
                if _parse_numeric(cell) is not None and (
                    row_has_usable_measure(row) or str(key).lower() != "row"
                ):
                    parsed = _parse_numeric(cell)
                    if parsed is not None:
                        values.append(parsed)
    return values


def draft_claim_consistency_gaps(
    user_query: str,
    draft: str,
    artifacts: list[dict[str, Any]],
) -> list[str]:
    """Deterministic synthesis checks for threshold/table grounding."""
    gaps: list[str] = []
    text = str(draft or "")
    lowered = text.lower()

    if artifacts_have_row_level_data(artifacts) and not artifacts_have_usable_row_data(artifacts):
        if any(word in lowered for word in ("yes", "sufficient", "enough", "available", "exceed")):
            gaps.append("Draft claims capacity from row results that are all NA or empty")

    threshold = _threshold_from_query(user_query)
    if threshold and ("enough" in lowered or "sufficient" in lowered or "exceed" in lowered):
        op, bound = threshold
        usable = _usable_numbers_from_artifacts(artifacts)
        if usable:
            if op == "gt" and not any(value > bound for value in usable):
                gaps.append(
                    f"Draft claims values exceed {bound} kW but no returned row satisfies that threshold"
                )
            if op == "lt" and not any(value < bound for value in usable):
                gaps.append(
                    f"Draft claims values are under {bound} kW but no returned row satisfies that threshold"
                )

    draft_numbers = _numbers_in_draft_table(text)
    artifact_numbers = _usable_numbers_from_artifacts(artifacts)
    if draft_numbers and artifact_numbers:
        artifact_set = {round(value, 2) for value in artifact_numbers}
        extras = [value for value in draft_numbers if round(value, 2) not in artifact_set]
        if extras and len(extras) >= max(1, len(draft_numbers) // 3):
            gaps.append("Draft table includes numeric values not present in row-level tool results")

    return list(dict.fromkeys(gaps))


_POWER_AVAILABILITY_DASHBOARD = "autopod_rows_availability"


def _artifact_text_blob(artifact: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("summary", "tool"):
        value = artifact.get(key)
        if value:
            parts.append(str(value))
    raw_ref = artifact.get("raw_ref")
    if isinstance(raw_ref, dict):
        for key in ("items", "dashboards", "results", "facts"):
            chunk = raw_ref.get(key)
            if isinstance(chunk, list):
                parts.extend(str(item) for item in chunk)
            elif chunk not in (None, ""):
                parts.append(str(chunk))
        if raw_ref.get("name"):
            parts.append(str(raw_ref["name"]))
    return "\n".join(parts).lower()


def discovery_answer_gaps(
    user_query: str,
    draft: str,
    artifacts: list[dict[str, Any]],
) -> list[str]:
    """Flag discovery answers that omit the primary power-availability dashboard."""
    if claim_class_from_query(user_query) != "discovery":
        return []
    draft_lower = str(draft or "").lower()
    if _POWER_AVAILABILITY_DASHBOARD in draft_lower:
        return []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        blob = _artifact_text_blob(artifact)
        if _POWER_AVAILABILITY_DASHBOARD in blob:
            return [
                "Name autopod_rows_availability as the primary dashboard for lab row power availability"
            ]
    return []
