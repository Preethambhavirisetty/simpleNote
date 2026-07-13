"""Light playbook router: YAML recipes emit normal structured plans."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.agent_workflow.evidence_grade import claim_class_from_query
from app.agent_workflow.parsing import enrich_plan_with_evidence
from app.agent_workflow.state import Plan, PlanStep

_PLAYBOOK_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def _load_playbooks() -> list[dict[str, Any]]:
    loaded: list[dict[str, Any]] = []
    for path in sorted(_PLAYBOOK_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        playbooks = data.get("playbooks")
        if isinstance(playbooks, list):
            loaded.extend(item for item in playbooks if isinstance(item, dict))
    return loaded


def _topic_hits(query: str, topics: list[str]) -> int:
    text = str(query or "").lower()
    return sum(1 for topic in topics if str(topic).lower() in text)


def _playbook_matches(playbook: dict[str, Any], query: str) -> bool:
    match = playbook.get("match") if isinstance(playbook.get("match"), dict) else {}
    claim = claim_class_from_query(query)
    allowed_claims = [str(item).lower() for item in (match.get("claims") or [])]
    if allowed_claims and claim not in allowed_claims:
        return False
    topics = match.get("topics") or []
    if topics and _topic_hits(query, topics) == 0 and claim != "discovery":
        return False
    return True


def _playbook_priority(playbook: dict[str, Any], query: str) -> int:
    """Higher wins ties — prefer the most specific recipe for the claim."""
    claim = claim_class_from_query(query)
    playbook_id = str(playbook.get("id") or "")
    priority = _topic_hits(query, playbook.get("match", {}).get("topics") or [])
    if claim == "discovery" and playbook_id == "dashboard_discovery":
        priority += 100
    if claim == "listing" and playbook_id == "row_power_listing":
        priority += 100
    if claim == "scalar" and playbook_id == "row_power_scalar":
        priority += 100
    if claim in {"existence", "threshold"} and playbook_id == "row_power_capacity":
        priority += 100
    return priority


def _build_steps(raw_steps: list[dict[str, Any]]) -> list[PlanStep]:
    steps: list[PlanStep] = []
    for item in raw_steps:
        if not isinstance(item, dict):
            continue
        step = PlanStep(
            title=str(item.get("title") or "Execute step"),
            action=str(item.get("action") or ""),
            tool_hint=str(item.get("tool_hint") or "auto"),
            expected_output=str(item.get("expected_output") or ""),
            stop_condition=str(item.get("stop_condition") or ""),
            required_tools=[str(tool) for tool in (item.get("required_tools") or []) if str(tool).strip()],
        )
        if item.get("require_row_level"):
            step["require_row_level"] = True
        steps.append(step)
    return steps


def resolve_playbook_plan(query: str) -> Plan | None:
    """Return a structured plan when a Splunk playbook matches the query."""
    cleaned = str(query or "").strip()
    if not cleaned:
        return None

    best: dict[str, Any] | None = None
    best_score = -1
    for playbook in _load_playbooks():
        if not isinstance(playbook, dict):
            continue
        if not _playbook_matches(playbook, cleaned):
            continue
        score = _playbook_priority(playbook, cleaned)
        if score > best_score:
            best = playbook
            best_score = score

    if not best:
        return None

    search_template = str(best.get("search_query_template") or "{query}")
    return enrich_plan_with_evidence(
        Plan(
            goal=str(best.get("goal") or cleaned),
            assumptions=[],
            risks=[],
            steps=_build_steps(best.get("steps") or []),
            acceptance_criteria=[str(item) for item in (best.get("acceptance_criteria") or []) if str(item).strip()],
            suggested_structure="",
            search_query=search_template.format(query=cleaned),
            evidence_required=str(best.get("evidence_required") or ""),
            playbook_id=str(best.get("id") or ""),
            dashboard=str(best.get("dashboard") or ""),
            raw_markdown=f"playbook:{best.get('id')}",
        )
    )
