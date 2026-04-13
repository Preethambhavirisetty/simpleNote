"""Strategy executors for query plans.

Each strategy receives retrieved chunks (or all user chunks) and produces
an optional deterministic fact that gets injected into the LLM prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from llama_index.core import Document as LlamaDocument

from pipeline.intent import QueryPlan


@dataclass
class StrategyResult:
    fact: str | None = None
    source_ids: list[str] = field(default_factory=list)
    skip_context: bool = False


def execute(plan: QueryPlan, all_chunks: list[LlamaDocument]) -> StrategyResult:
    """Dispatch to the right strategy executor based on the plan."""
    handler = _STRATEGY_MAP.get(plan.strategy, _semantic)
    return handler(plan, all_chunks)


# ── keyword_count ─────────────────────────────────────────────────────────

def _keyword_count(plan: QueryPlan, chunks: list[LlamaDocument]) -> StrategyResult:
    if not plan.search_term:
        return StrategyResult()

    term = plan.search_term.strip().lower()
    pattern = re.compile(re.escape(term), re.IGNORECASE)

    total = 0
    matched_note_ids: list[str] = []

    for chunk in chunks:
        count = len(pattern.findall(chunk.text))
        if count > 0:
            total += count
            note_id = chunk.metadata.get("note_id")
            if note_id and note_id not in matched_note_ids:
                matched_note_ids.append(note_id)

    if total == 0:
        fact = f"The phrase '{plan.search_term}' does not appear in your notes."
    elif total == 1:
        fact = f"The phrase '{plan.search_term}' appears exactly 1 time in your notes."
    else:
        fact = f"The phrase '{plan.search_term}' appears exactly {total} times in your notes."

    return StrategyResult(fact=fact, source_ids=matched_note_ids, skip_context=True)


# ── temporal ──────────────────────────────────────────────────────────────

def _temporal(plan: QueryPlan, chunks: list[LlamaDocument]) -> StrategyResult:
    entries: list[tuple[int, str, str]] = []
    for chunk in chunks:
        ts = chunk.metadata.get("created_at")
        if not ts:
            continue
        note_id = chunk.metadata.get("note_id", "")
        note_title = chunk.metadata.get("note_title", "Untitled")
        entries.append((int(ts), note_id, note_title))

    if not entries:
        return StrategyResult()

    entries.sort(key=lambda e: e[0])
    unique_notes: dict[str, tuple[int, str]] = {}
    for ts, nid, title in entries:
        if nid not in unique_notes:
            unique_notes[nid] = (ts, title)

    lines: list[str] = []
    source_ids: list[str] = []
    for nid, (ts, title) in sorted(unique_notes.items(), key=lambda x: x[1][0]):
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%b %d, %Y")
        lines.append(f'- "{title}" on {dt}')
        source_ids.append(nid)

    fact = "Matching notes in chronological order:\n" + "\n".join(lines)
    return StrategyResult(fact=fact, source_ids=source_ids)


# ── listing ───────────────────────────────────────────────────────────────

def _listing(plan: QueryPlan, chunks: list[LlamaDocument]) -> StrategyResult:
    seen: dict[str, str] = {}
    for chunk in chunks:
        note_id = chunk.metadata.get("note_id", "")
        title = chunk.metadata.get("note_title", "Untitled")
        if note_id and note_id not in seen:
            seen[note_id] = title

    if not seen:
        return StrategyResult()

    lines = [f"- {title}" for title in seen.values()]
    fact = f"Found {len(seen)} matching note(s):\n" + "\n".join(lines)
    return StrategyResult(fact=fact, source_ids=list(seen.keys()))


# ── semantic (pass-through) ───────────────────────────────────────────────

def _semantic(_plan: QueryPlan, _chunks: list[LlamaDocument]) -> StrategyResult:
    return StrategyResult()


# ── Dispatch table ────────────────────────────────────────────────────────

_STRATEGY_MAP = {
    "keyword_count": _keyword_count,
    "temporal": _temporal,
    "listing": _listing,
    "semantic": _semantic,
}
