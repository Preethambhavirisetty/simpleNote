from __future__ import annotations

import hashlib
from typing import Any

from app.agent_workflow.config import AgentConfig
from app.agent_workflow.state import AgentState, Fact


def fact_extractor_node(state: AgentState, *, config: AgentConfig) -> dict[str, Any]:
    """Convert raw artifacts into compact facts for later LLM nodes."""
    # This node is deterministic on purpose. Downstream nodes should reason over
    # small facts with provenance, not full tool payloads that can explode context.
    artifacts = list(state.get("artifacts") or [])
    facts = _extract_facts(artifacts, max_facts=config.policy.context.max_artifacts_in_prompt * 3)
    if not facts and state.get("draft_answer"):
        facts = [
            {
                "id": _fact_id("draft", str(state.get("draft_answer") or "")),
                "text": str(state.get("draft_answer") or "").strip(),
                "source_artifact_id": "",
                "tool": "executor_draft",
                "source_ref": {},
                "confidence": 0.35,
                "truncated_source": False,
            }
        ]
    return {
        "facts": facts,
        "phase": "synthesizing",
        "events": [
            {
                "step": "fact_extractor.completed",
                "fact_count": len(facts),
                "artifact_count": len(artifacts),
                "truncated_source_count": sum(1 for fact in facts if fact.get("truncated_source")),
            }
        ],
    }


def _extract_facts(artifacts: list[dict[str, Any]], *, max_facts: int) -> list[Fact]:
    """Pull concise, source-linked fact lines from scored artifacts."""
    facts: list[Fact] = []
    ranked = sorted(
        artifacts,
        key=lambda artifact: float(artifact.get("composite_score") or 0.0),
        reverse=True,
    )
    for artifact in ranked:
        if len(facts) >= max_facts:
            break
        raw_ref = artifact.get("raw_ref") if isinstance(artifact.get("raw_ref"), dict) else {}
        if raw_ref.get("type") == "list" and isinstance(raw_ref.get("total"), int):
            facts.append(_make_fact(artifact, f"{artifact.get('tool', 'tool')} returned {raw_ref['total']} item(s)."))
        for line in _summary_lines(str(artifact.get("summary") or "")):
            if len(facts) >= max_facts:
                break
            facts.append(_make_fact(artifact, line))
    return facts


def _summary_lines(summary: str) -> list[str]:
    """Normalize artifact summary text into short factual lines."""
    lines: list[str] = []
    for raw in summary.splitlines():
        line = raw.strip().lstrip("-*").strip()
        if not line or line.lower().startswith("[truncated]"):
            continue
        if len(line) > 500:
            line = line[:497].rstrip() + "..."
        lines.append(line)
    if not lines and summary.strip():
        text = summary.strip()
        lines.append(text[:497].rstrip() + "..." if len(text) > 500 else text)
    return lines


def _make_fact(artifact: dict[str, Any], text: str) -> Fact:
    """Create one provenance-bearing fact from an artifact line."""
    return {
        "id": _fact_id(str(artifact.get("id") or artifact.get("tool") or "artifact"), text),
        "text": text,
        "source_artifact_id": str(artifact.get("id") or ""),
        "tool": str(artifact.get("tool") or "tool"),
        "source_ref": artifact.get("source_ref") if isinstance(artifact.get("source_ref"), dict) else {},
        "confidence": float(artifact.get("composite_score") or 0.0),
        "truncated_source": bool(artifact.get("truncated")),
    }


def _fact_id(seed: str, text: str) -> str:
    """Return a stable compact id for a fact."""
    digest = hashlib.sha1(f"{seed}:{text}".encode("utf-8")).hexdigest()[:12]
    return f"fact_{digest}"
