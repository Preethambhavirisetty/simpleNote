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
    # generous per-fact limits cannot overflow the model's context window. The
    # synthesizer also includes verbatim primary-evidence summaries under its own
    # budget, so facts get ~a third of the window here and the two together stay
    # comfortably inside it.
    max_total_fact_chars = max(4000, int(config.policy.max_context_tokens))
    facts = _extract_facts(
        artifacts,
        max_facts=config.policy.context.max_artifacts_in_prompt * 3,
        max_fact_chars=max_fact_chars,
        max_total_chars=max_total_fact_chars,
    )
    # Evidence compressed into running memory mid-loop must still reach
    # synthesis/review; seed it as facts ahead of the per-artifact facts.
    # Call provenance (which tools ran, with which arguments) rides along so the
    # answer states applied filters truthfully — the draft cannot claim a filter
    # was used when the recorded call shows it was not.
    facts = (
        _memory_facts(str(state.get("running_summary") or ""), max_fact_chars)
        + _call_provenance_facts(list(state.get("tool_calls") or []), max_fact_chars)
        + facts
    )
    used_draft_fallback = False
    draft = str(state.get("draft_answer") or "").strip()
    if not facts and draft and not _looks_like_action_json(draft):
        # Last resort only, and never for unparsed action JSON — distilling that
        # as a "fact" feeds the model's own control tokens back as evidence.
        used_draft_fallback = True
        facts = [
            {
                "id": _fact_id("draft", draft),
                "text": draft,
                "source_artifact_id": "",
                "tool": "executor_draft",
                "source_ref": {},
                "confidence": 0.35,
                "truncated_source": False,
            }
        ]
    tool_counts: dict[str, int] = {}
    for fact in facts:
        tool = str(fact.get("tool") or "")
        if tool:
            tool_counts[tool] = tool_counts.get(tool, 0) + 1
    preview = [str(fact.get("text") or "").strip()[:140] for fact in facts[:3] if str(fact.get("text") or "").strip()]
    return {
        "facts": facts,
        "phase": "synthesizing",
        "events": [
            {
                "step": "fact_extractor.completed",
                "fact_count": len(facts),
                "artifact_count": len(artifacts),
                "truncated_source_count": sum(1 for fact in facts if fact.get("truncated_source")),
                "tools": sorted(tool_counts),
                "tool_fact_counts": tool_counts,
                "used_draft_fallback": used_draft_fallback,
                "preview": preview,
            }
        ],
    }


def _looks_like_action_json(text: str) -> bool:
    """Return whether a draft is really unparsed executor action JSON."""
    stripped = text.lstrip("` \n")
    return stripped.startswith("{") and '"action"' in stripped[:200]


_MAX_PROVENANCE_CALLS = 8


def _call_provenance_facts(tool_calls: list[dict[str, Any]], max_fact_chars: int) -> list[Fact]:
    """One fact per recent successful tool call recording the arguments used.

    This is the ground truth for "which filters were actually applied" — the
    synthesizer and reviewer see e.g. ``get_panel_data was called with
    {"panel_id": 77, "panel_tokens": {"site": "RTP"}}`` and cannot honestly
    describe a filter that never appears in any recorded call.
    """
    facts: list[Fact] = []
    successful = [r for r in tool_calls if str(r.get("status") or "") == "ok" and r.get("name")]
    for record in successful[-_MAX_PROVENANCE_CALLS:]:
        name = str(record.get("name"))
        args = str(record.get("args_preview") or "{}")
        facts.append(
            {
                "id": _fact_id("tool_call", f"{name}:{args}"),
                "text": _clip(f"{name} was called with arguments {args}", max_fact_chars),
                "source_artifact_id": "",
                "tool": name,
                "source_ref": {},
                "confidence": 1.0,
                "truncated_source": False,
            }
        )
    return facts


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
    """Pull concise, source-linked fact lines from scored artifacts.

    Budget is allocated fairly: every artifact is guaranteed a floor share
    before higher-ranked artifacts consume the remainder. A greedy walk let one
    fat catalog result (e.g. a 30-item listing) exhaust the whole budget and
    starve the newest evidence — the exact artifact the question depends on —
    out of synthesis entirely.
    """
    ranked = sorted(
        artifacts,
        key=lambda artifact: float(artifact.get("composite_score") or 0.0),
        reverse=True,
    )
    if not ranked or max_facts <= 0:
        return []
    per_source = [_artifact_facts(artifact, max_fact_chars, cap=max_facts) for artifact in ranked]
    floor = max(1, max_facts // len(ranked))

    facts: list[Fact] = []
    used_chars = 0

    def budget_left() -> bool:
        return len(facts) < max_facts and (not max_total_chars or used_chars < max_total_chars)

    def take(source: list[Fact], count: int) -> None:
        nonlocal used_chars
        while source and count > 0 and budget_left():
            fact = source.pop(0)
            facts.append(fact)
            used_chars += len(str(fact.get("text") or ""))
            count -= 1

    # Round 1: guaranteed floor per artifact, best-ranked first.
    for source in per_source:
        take(source, floor)
    # Round 2: leftover budget flows to the best-ranked artifacts' remaining facts.
    for source in per_source:
        take(source, max_facts)
    return facts


def _artifact_facts(artifact: dict[str, Any], max_fact_chars: int, *, cap: int) -> list[Fact]:
    """Produce this artifact's candidate facts (bounded), best material first."""
    facts: list[Fact] = []
    raw_ref = artifact.get("raw_ref") if isinstance(artifact.get("raw_ref"), dict) else {}
    if raw_ref.get("type") == "list" and isinstance(raw_ref.get("total"), int):
        facts.append(_make_fact(artifact, f"{artifact.get('tool', 'tool')} returned {raw_ref['total']} item(s)."))

    # Prefer structured facts a tool supplies, then generic collections, and
    # only fall back to summary line-splitting when nothing structured exists.
    structured = _structured_entries(raw_ref, _FACT_PATHS)
    if structured is not None:
        for entry in structured[: cap - len(facts)]:
            fact = _make_structured_fact(artifact, entry, max_fact_chars)
            if fact["text"]:
                facts.append(fact)
        return facts

    rows = _structured_entries(raw_ref, _COLLECTION_PATHS)
    if rows is not None:
        for entry in rows[: cap - len(facts)]:
            text = _entry_text(entry)
            if text:
                facts.append(_make_fact(artifact, _clip(text, max_fact_chars)))
        return facts

    for line in _summary_lines(str(artifact.get("summary") or ""), max_fact_chars):
        if len(facts) >= cap:
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
