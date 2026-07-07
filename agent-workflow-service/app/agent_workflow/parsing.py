from __future__ import annotations

import json
import re
from typing import Any

from app.agent_workflow.state import Plan, PlanStep, ReviewResult


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
        raw_markdown=text,
    )


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


def parse_executor_action(text: str) -> dict[str, Any]:
    """Parse the executor JSON action and fall back to a draft answer when needed."""
    cleaned = text.strip()
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
    return {"action": "draft_answer", "answer": cleaned}


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
    return [item.strip() for item in value.split(",") if item.strip()]
