from __future__ import annotations

import json
import re
from typing import Any

from app.agent_workflow.state import Plan, PlanStep, ReviewResult


def normalize_tool_name(name: Any) -> str:
    """Strip wrapping quotes/backticks so planner-required tools match tool_calls."""
    return str(name or "").strip().strip("`\"'")


def parse_plan_markdown(text: str) -> Plan:
    """Parse planner markdown into the structured plan used by the graph."""
    sections = _split_sections(text)
    steps = _parse_steps(sections.get("execution plan", ""))
    return Plan(
        goal=sections.get("goal", "").strip(),
        assumptions=_bullets(sections.get("assumptions", "")),
        risks=_bullets(sections.get("risks / edge cases") or sections.get("risks and edge cases", "")),
        steps=steps,
        acceptance_criteria=_bullets(sections.get("acceptance criteria", "")),
        suggested_structure=sections.get("suggested user-facing structure", "").strip(),
        search_query=_first_line(sections.get("search query", "")),
        evidence_required=_first_line(sections.get("evidence required", "")),
        raw_markdown=text,
    )


def enrich_plan_with_evidence(plan: Plan) -> Plan:
    """Tag plan steps that must return row-level evidence before the run can finish."""
    enriched = dict(plan)
    required = str(enriched.get("evidence_required") or "").strip().lower()
    if required in {"row", "row_level", "rows"}:
        steps = []
        for step in enriched.get("steps") or []:
            item = dict(step)
            if any(
                token in str(item.get("action") or "").lower()
                for token in ("query", "panel data", "get_panel_data", "fetch", "pull live")
            ) or item.get("require_row_level"):
                item["require_row_level"] = True
                if not str(item.get("stop_condition") or "").strip():
                    item["stop_condition"] = "Row-level tool results have been returned for this step"
            steps.append(item)
        enriched["steps"] = steps
    return enriched  # type: ignore[return-value]


def parse_review_markdown(text: str) -> ReviewResult:
    """Parse reviewer markdown into a structured review result."""
    sections = _split_sections(text)
    verdict = "REVISE"
    verdict_block = sections.get("verdict", "")
    for option in ("APPROVE", "REVISE", "REJECT"):
        if option in verdict_block.upper():
            verdict = option
            break
    return ReviewResult(
        verdict=verdict,
        issues=_bullets(sections.get("issues found", "")),
        missing_evidence=_bullets(sections.get("missing evidence", "")),
        required_changes=_numbered(sections.get("required changes", "")),
        approved_answer=sections.get("approved answer", "").strip(),
        raw_markdown=text,
    )


def strip_code_fence(text: str) -> str:
    """Remove a wrapping ```/```json code fence from LLM output."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned


def extract_json_object(text: str, *, prefer_key: str = "") -> dict[str, Any] | None:
    """Return the first JSON object found in LLM output, or None.

    Models sometimes emit several JSON objects in one turn or wrap the object in
    prose. Objects are decoded one at a time (raw_decode from each ``{``) — a
    greedy ``{.*}`` regex would span multiple objects and fail to parse. When
    ``prefer_key`` is set, the first object carrying that key wins over earlier
    objects without it.
    """
    cleaned = strip_code_fence(text)
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    first_dict: dict[str, Any] | None = None
    pos = cleaned.find("{")
    while pos != -1:
        try:
            data, end = decoder.raw_decode(cleaned, pos)
        except json.JSONDecodeError:
            pos = cleaned.find("{", pos + 1)
            continue
        if isinstance(data, dict):
            if not prefer_key or data.get(prefer_key):
                return data
            first_dict = first_dict or data
        pos = cleaned.find("{", end)
    return first_dict


def parse_executor_action(text: str) -> dict[str, Any]:
    """Parse the executor JSON action and fall back to a draft answer when needed."""
    data = extract_json_object(text, prefer_key="action")
    if data is not None:
        return data
    return {"action": "draft_answer", "answer": strip_code_fence(text)}


def _split_sections(text: str) -> dict[str, str]:
    """Helper for split sections."""
    sections: dict[str, str] = {}
    current = ""
    body: list[str] = []
    for line in text.splitlines():
        if line.startswith("### "):
            if current:
                sections[current.lower()] = "\n".join(body).strip()
            current = line.removeprefix("### ").strip()
            body = []
        else:
            body.append(line)
    if current:
        sections[current.lower()] = "\n".join(body).strip()
    return sections


def _first_line(block: str) -> str:
    """Return the first non-empty line of a section, stripped of list markers."""
    for line in block.splitlines():
        cleaned = line.strip().lstrip("-*").strip()
        if cleaned:
            return cleaned
    return ""


def _bullets(block: str) -> list[str]:
    """Helper for bullets."""
    items = []
    for line in block.splitlines():
        line = line.strip()
        if line.startswith("- "):
            items.append(line[2:].strip())
    if not items and block.strip() and block.strip().lower() != "none":
        items.append(block.strip())
    return items


def _numbered(block: str) -> list[str]:
    """Helper for numbered."""
    items = []
    for line in block.splitlines():
        line = line.strip()
        if re.match(r"^\d+\.", line):
            items.append(re.sub(r"^\d+\.\s*", "", line))
    if not items and block.strip().lower() not in {"", "none"}:
        items.append(block.strip())
    return items


def _parse_steps(block: str) -> list[PlanStep]:
    """Parse steps into the shape used by the workflow."""
    steps: list[PlanStep] = []
    chunks = re.split(r"\n(?=\d+\.\s+\*\*)", block)
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        title_match = re.search(r"\d+\.\s+\*\*(.+?)\*\*", chunk)
        title = title_match.group(1).strip() if title_match else chunk.splitlines()[0][:80]
        steps.append(
            PlanStep(
                title=title,
                action=_field(chunk, "Action"),
                tool_hint=_field(chunk, "Tool hint"),
                expected_output=_field(chunk, "Expected output"),
                stop_condition=_field(chunk, "Stop condition"),
                required_tools=_csv_items(_field(chunk, "Required tools")),
            )
        )
    if not steps and block.strip():
        steps.append(PlanStep(title="Execute request", action=block.strip(), tool_hint="none"))
    return steps


def _field(block: str, label: str) -> str:
    """Helper for field."""
    pattern = rf"{label}\s*[—:-]\s*(.+)"
    match = re.search(pattern, block, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _csv_items(value: str) -> list[str]:
    """Helper for csv items."""
    if not value:
        return []
    items = []
    for item in value.split(","):
        name = normalize_tool_name(item)
        if name and name.lower() not in {"none", "n/a"}:
            items.append(name)
    return items
