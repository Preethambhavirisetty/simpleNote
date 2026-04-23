"""Strategy executors for query plans.

Each strategy receives retrieved chunks (or all user chunks) and produces
an optional deterministic fact that gets injected into the LLM prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from llama_index.core import Document as LlamaDocument

from handlers.strategies.keyword_count import KeywordExtractor
from pipeline.intent import QueryPlan


@dataclass
class StrategyResult:
    fact: str | None = None
    source_ids: list[str] = field(default_factory=list)
    skip_context: bool = False


def execute(plan: QueryPlan, all_chunks: list[LlamaDocument], query: str = "") -> StrategyResult:
    """Dispatch to the right strategy executor based on the plan."""
    handler = _STRATEGY_MAP.get(plan.strategy, _semantic)
    return handler(plan, all_chunks, query)


# ── helpers ───────────────────────────────────────────────────────────────

def _resolve_term(plan: QueryPlan, query: str) -> str | None:
    """Extract the target term from plan metadata, falling back to regex on the raw query."""
    term = plan.search_term or (plan.slots.get("topic") if plan.slots else None)
    if term:
        return term.strip().strip("'\"")

    if query:
        return KeywordExtractor.extract(query)
    return None


# ── keyword_count ─────────────────────────────────────────────────────────

def _keyword_count(plan: QueryPlan, chunks: list[LlamaDocument], query: str = "") -> StrategyResult:
    term = _resolve_term(plan, query)
    if not term:
        return StrategyResult(
            fact="I couldn't determine which word or phrase to count. "
                 'Could you rephrase? For example: "how many notes mention **budget**?"',
            skip_context=True,
        )

    try:
        pattern = re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)
    except re.error:
        pattern = re.compile(re.escape(term), re.IGNORECASE)

    total = 0
    matched_notes: dict[str, dict] = {}

    for chunk in chunks:
        count = len(pattern.findall(chunk.text))
        if count > 0:
            total += count
            note_id = chunk.metadata.get("note_id")
            if note_id:
                if note_id not in matched_notes:
                    matched_notes[note_id] = {
                        "count": 0,
                        "title": chunk.metadata.get("note_title", "Untitled"),
                    }
                matched_notes[note_id]["count"] += count

    matched_note_ids = list(matched_notes.keys())

    if total == 0:
        partial = re.compile(re.escape(term), re.IGNORECASE)
        partial_count = sum(len(partial.findall(c.text)) for c in chunks)

        if partial_count > 0:
            fact = (
                f"The exact phrase '{term}' does not appear in your notes, "
                f"but partial matches were found {partial_count} time(s). "
                f"Try a shorter or different form of the word."
            )
        else:
            fact = f"'{term}' does not appear in any of your notes."

    elif total == 1:
        note = list(matched_notes.values())[0]
        fact = (
            f"'{term}' appears 1 time in the note "
            f"\"{note['title']}\"."
        )
    else:
        fact = (
            f"'{term}' appears {total} times "
            f"across {len(matched_notes)} note(s)."
        )

        if 1 < len(matched_notes) <= 7:
            breakdown = sorted(
                matched_notes.items(),
                key=lambda x: x[1]["count"],
                reverse=True,
            )
            lines = [
                f"  - \"{info['title']}\": {info['count']} mention(s)"
                for _, info in breakdown
            ]
            fact += "\n" + "\n".join(lines)

    return StrategyResult(fact=fact, source_ids=matched_note_ids, skip_context=True)


# ── temporal ──────────────────────────────────────────────────────────────

def _temporal(plan: QueryPlan, chunks: list[LlamaDocument], query: str = "") -> StrategyResult:
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
    return StrategyResult(fact=fact, source_ids=source_ids, skip_context=True)


# ── listing ───────────────────────────────────────────────────────────────

def _listing(plan: QueryPlan, chunks: list[LlamaDocument], query: str = "") -> StrategyResult:
    seen: dict[str, tuple[str, str]] = {}
    for chunk in chunks:
        note_id = chunk.metadata.get("note_id", "")
        title = chunk.metadata.get("note_title", "Untitled")
        folder = chunk.metadata.get("folder_title", "")
        if note_id and note_id not in seen:
            seen[note_id] = (title, folder)

    if not seen:
        return StrategyResult()

    lines = []
    for title, folder in seen.values():
        if folder:
            lines.append(f"- {title} (in {folder})")
        else:
            lines.append(f"- {title}")

    fact = f"Found {len(seen)} matching note(s):\n" + "\n".join(lines)
    return StrategyResult(fact=fact, source_ids=list(seen.keys()), skip_context=True)


# ── presence_check ────────────────────────────────────────────────────────

def _presence_check(plan: QueryPlan, chunks: list[LlamaDocument], query: str = "") -> StrategyResult:
    term = _resolve_term(plan, query)
    if not term:
        return StrategyResult(
            fact="I couldn't determine what to look for. "
                 'Could you rephrase? For example: "did I mention **travel**?"',
            skip_context=True,
        )

    try:
        pattern = re.compile(r"\b" + re.escape(term.strip()) + r"\b", re.IGNORECASE)
    except re.error:
        pattern = re.compile(re.escape(term.strip()), re.IGNORECASE)

    matched: list[tuple[str, str, str]] = []
    for chunk in chunks:
        if pattern.search(chunk.text):
            note_id = chunk.metadata.get("note_id", "")
            note_title = chunk.metadata.get("note_title", "Untitled")
            folder = chunk.metadata.get("folder_title", "")
            if note_id and not any(m[0] == note_id for m in matched):
                matched.append((note_id, note_title, folder))

    if not matched:
        return StrategyResult(
            fact=f'No — the term "{term}" does not appear in any of your notes.',
            skip_context=True,
        )

    if len(matched) == 1:
        nid, title, folder = matched[0]
        location = f" (in {folder})" if folder else ""
        fact = f'Yes — found in "{title}"{location}.'
    else:
        lines = []
        for _, title, folder in matched:
            loc = f" (in {folder})" if folder else ""
            lines.append(f'- "{title}"{loc}')
        fact = f'Yes — found in {len(matched)} note(s):\n' + "\n".join(lines)

    return StrategyResult(
        fact=fact,
        source_ids=[m[0] for m in matched],
        skip_context=True,
    )


# ── corpus_stats ──────────────────────────────────────────────────────────

def _corpus_stats(_plan: QueryPlan, chunks: list[LlamaDocument], query: str = "") -> StrategyResult:
    if not chunks:
        return StrategyResult(
            fact="Your note collection is empty.", skip_context=True,
        )

    note_info: dict[str, tuple[str, int]] = {}
    folders: set[str] = set()
    total_words = 0

    for chunk in chunks:
        note_id = chunk.metadata.get("note_id", "")
        title = chunk.metadata.get("note_title", "Untitled")
        folder = chunk.metadata.get("folder_title")
        words = len(chunk.text.split())
        total_words += words

        if note_id:
            prev_words = note_info[note_id][1] if note_id in note_info else 0
            note_info[note_id] = (title, prev_words + words)
        if folder:
            folders.add(folder)

    num_notes = len(note_info)
    num_folders = len(folders)

    parts = [f"You have {num_notes} note(s)"]
    if num_folders:
        parts[0] += f" across {num_folders} folder(s)"

    parts.append(f"Total word count: ~{total_words:,}")

    if note_info:
        largest_id = max(note_info, key=lambda k: note_info[k][1])
        smallest_id = min(note_info, key=lambda k: note_info[k][1])
        lg_title, lg_words = note_info[largest_id]
        sm_title, sm_words = note_info[smallest_id]
        parts.append(f"Largest note: \"{lg_title}\" (~{lg_words:,} words)")
        parts.append(f"Smallest note: \"{sm_title}\" (~{sm_words:,} words)")

    fact = ". ".join(parts) + "."
    return StrategyResult(fact=fact, skip_context=True)


# ── semantic (pass-through) ───────────────────────────────────────────────

def _semantic(_plan: QueryPlan, _chunks: list[LlamaDocument], query: str = "") -> StrategyResult:
    return StrategyResult()


# ── Dispatch table ────────────────────────────────────────────────────────

_STRATEGY_MAP = {
    "keyword_count":  _keyword_count,
    "temporal":       _temporal,
    "listing":        _listing,
    "presence_check": _presence_check,
    "corpus_stats":   _corpus_stats,
    "semantic":       _semantic,
}
