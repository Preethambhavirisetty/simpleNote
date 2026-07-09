from __future__ import annotations

import hashlib
from typing import Any

from app.agent_workflow.config import AgentConfig
from app.agent_workflow.state import AgentState, Fact


# Structured facts, when a tool provides them, are preferred over line-splitting.
# These are generic contract locations; app/MCP tools opt in by populating them.
# Rich per-tool extractors are intended to live MCP-side later, not here.
_FACT_PATHS: tuple[tuple[str, ...], ...] = (
    ("facts",),
    ("data", "facts"),
    ("display", "facts"),
    ("metadata", "facts"),
)
_COLLECTION_PATHS: tuple[tuple[str, ...], ...] = (
    ("display", "tables"),
    ("items",),
    ("results",),
    ("rows",),
    ("panels",),
)
_MAX_FACT_CHARS = 500


def fact_extractor_node(state: AgentState, *, config: AgentConfig) -> dict[str, Any]:
    """Convert raw artifacts into compact facts for later LLM nodes."""
    # This node is deterministic on purpose. Downstream nodes should reason over
    # small facts with provenance, not full tool payloads that can explode context.
    artifacts = list(state.get("artifacts") or [])
    max_fact_chars = int(config.policy.truncation.max_fact_chars)
    # Total facts budget bounds the (otherwise un-budgeted) synthesizer prompt so
    # generous per-fact limits cannot overflow the model's context window. Facts
    # are held to roughly half the window (~2 chars/token here), leaving room for
    # the rest of the prompt and the model's own output.
    max_total_fact_chars = max(8000, int(config.policy.max_context_tokens) * 2)
    facts = _extract_facts(
        artifacts,
        max_facts=config.policy.context.max_artifacts_in_prompt * 3,
        max_fact_chars=max_fact_chars,
        max_total_chars=max_total_fact_chars,
    )
    # Evidence compressed into running memory mid-loop must still reach
    # synthesis/review; seed it as facts ahead of the per-artifact facts.
    facts = _memory_facts(str(state.get("running_summary") or ""), max_fact_chars) + facts
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


def _memory_facts(running_summary: str, max_fact_chars: int) -> list[Fact]:
    """Turn the running-summary memo into compact facts for downstream nodes."""
    facts: list[Fact] = []
    for line in _summary_lines(running_summary, max_fact_chars):
        # Skip the memo's section headers ("Confirmed facts:", etc.).
        if line.endswith(":") and len(line) <= 40:
            continue
        facts.append(
            {
                "id": _fact_id("running_summary", line),
                "text": line,
                "source_artifact_id": "",
                "tool": "running_summary",
                "source_ref": {},
                "confidence": 0.5,
                "truncated_source": False,
            }
        )
    return facts


def _extract_facts(
    artifacts: list[dict[str, Any]],
    *,
    max_facts: int,
    max_fact_chars: int,
    max_total_chars: int = 0,
) -> list[Fact]:
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
        # Stop once the aggregate facts payload reaches the total budget; the
        # highest-scoring artifacts are processed first, so the least useful drop.
        if max_total_chars and sum(len(str(fact.get("text") or "")) for fact in facts) >= max_total_chars:
            break
        raw_ref = artifact.get("raw_ref") if isinstance(artifact.get("raw_ref"), dict) else {}
        if raw_ref.get("type") == "list" and isinstance(raw_ref.get("total"), int):
            facts.append(_make_fact(artifact, f"{artifact.get('tool', 'tool')} returned {raw_ref['total']} item(s)."))
        remaining = max_facts - len(facts)
        if remaining <= 0:
            break

        # Prefer structured facts a tool supplies, then generic collections, and
        # only fall back to summary line-splitting when nothing structured exists.
        structured = _structured_entries(raw_ref, _FACT_PATHS)
        if structured is not None:
            for entry in structured[:remaining]:
                fact = _make_structured_fact(artifact, entry, max_fact_chars)
                if fact["text"]:
                    facts.append(fact)
            continue

        rows = _structured_entries(raw_ref, _COLLECTION_PATHS)
        if rows is not None:
            for entry in rows[:remaining]:
                text = _entry_text(entry)
                if text:
                    facts.append(_make_fact(artifact, _clip(text, max_fact_chars)))
            continue

        for line in _summary_lines(str(artifact.get("summary") or ""), max_fact_chars):
            if len(facts) >= max_facts:
                break
            facts.append(_make_fact(artifact, line))
    return facts


def _structured_entries(raw_ref: dict[str, Any], paths: tuple[tuple[str, ...], ...]) -> list[Any] | None:
    """Return the first non-empty list found at any of the given nested paths."""
    for path in paths:
        node = _dig(raw_ref, path)
        if isinstance(node, list) and node:
            return node
    return None


def _dig(obj: Any, path: tuple[str, ...]) -> Any:
    """Walk a nested dict path, returning None if any hop is missing."""
    current = obj
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _entry_text(entry: Any) -> str:
    """Render one collection entry (row/item/panel) as a compact fact line."""
    if isinstance(entry, dict):
        parts: list[str] = []
        for key, value in entry.items():
            if value in (None, "", [], {}) or isinstance(value, (dict, list)):
                continue
            parts.append(f"{key}={value}")
            if len(parts) >= 8:
                break
        return ", ".join(parts)
    if isinstance(entry, (str, int, float, bool)):
        return str(entry).strip()
    return ""


def _summary_lines(summary: str, max_fact_chars: int) -> list[str]:
    """Normalize artifact summary text into short factual lines."""
    lines: list[str] = []
    for raw in summary.splitlines():
        line = raw.strip().lstrip("-*").strip()
        if not line or line.lower().startswith("[truncated]"):
            continue
        lines.append(_clip(line, max_fact_chars))
    if not lines and summary.strip():
        lines.append(_clip(summary.strip(), max_fact_chars))
    return lines


def _clip(text: str, max_fact_chars: int) -> str:
    """Trim a fact line to the configured maximum fact length."""
    limit = max_fact_chars if max_fact_chars and max_fact_chars > 0 else _MAX_FACT_CHARS
    if len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


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


def _make_structured_fact(artifact: dict[str, Any], entry: Any, max_fact_chars: int) -> Fact:
    """Create a fact from a tool-supplied structured fact entry."""
    if isinstance(entry, dict):
        text = str(
            entry.get("text")
            or entry.get("summary")
            or entry.get("label")
            or _entry_text(entry)
            or ""
        ).strip()
        fact = _make_fact(artifact, _clip(text, max_fact_chars))
        if "confidence" in entry:
            try:
                fact["confidence"] = float(entry["confidence"])
            except (TypeError, ValueError):
                pass
        source_ref = entry.get("source_ref")
        if isinstance(source_ref, dict) and source_ref:
            fact["source_ref"] = source_ref
        return fact
    return _make_fact(artifact, _clip(str(entry).strip(), max_fact_chars))


def _fact_id(seed: str, text: str) -> str:
    """Return a stable compact id for a fact."""
    digest = hashlib.sha1(f"{seed}:{text}".encode("utf-8")).hexdigest()[:12]
    return f"fact_{digest}"
