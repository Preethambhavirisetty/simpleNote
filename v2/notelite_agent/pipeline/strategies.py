"""Strategy executors for query plans.

Each strategy receives retrieved chunks (or all user chunks) and produces
an optional deterministic fact that gets injected into the LLM prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from llama_index.core import Document as LlamaDocument

from handlers.strategies.keyword_count import KeywordCounter, KeywordExtractor, TermCount
from pipeline.intent import QueryPlan


@dataclass
class StrategyResult:
    fact: str | None = None
    source_ids: list[str] = field(default_factory=list)
    skip_context: bool = False
    citations: list[dict] = field(default_factory=list)
    extracted_terms: list[str] = field(default_factory=list)


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

def _keyword_count(
    plan: QueryPlan,
    chunks: list[LlamaDocument],
    query: str = "",
) -> StrategyResult:
    terms = KeywordExtractor.extract_multiple(query) if query else []

    if not terms:
        term = _resolve_term(plan, query)
        terms = [term] if term else []

    if not terms:
        return StrategyResult(
            fact="I couldn't determine which word or phrase to count. "
                 'Try something like: "how many notes mention **budget**?"',
            skip_context=True,
        )

    count_type = KeywordCounter.determine_count_type(query)
    results = KeywordCounter.count_multiple(terms, chunks)

    all_source_ids: list[str] = []
    for tc in results.values():
        all_source_ids.extend(k for k in tc.matched_notes if k not in all_source_ids)

    if len(terms) >= 2:
        fact = _format_comparative(terms, results, count_type)
    else:
        fact = _format_single(terms[0], results[terms[0]], count_type)

    citations = _build_citations(results)
    return StrategyResult(
        fact=fact, source_ids=all_source_ids,
        skip_context=True, citations=citations,
        extracted_terms=terms,
    )


def _build_citations(results: dict[str, TermCount]) -> list[dict]:
    """Build structured citation list from count results for SSE output."""
    seen: set[str] = set()
    citations: list[dict] = []
    for tc in results.values():
        for note_id, info in tc.matched_notes.items():
            if note_id not in seen:
                seen.add(note_id)
                citations.append({
                    "note_id": note_id,
                    "title": info.get("title", "Untitled"),
                    "folder": info.get("folder", ""),
                    "folder_id": info.get("folder_id", ""),
                })
    return citations



def _format_single(term: str, tc: TermCount, count_type: str) -> str:
    if tc.mention_count == 0:
        return f"'{term}' does not appear in any of your notes."

    if tc.mention_count == 1:
        note = list(tc.matched_notes.values())[0]
        folder = note.get("folder", "")
        loc = f" in folder '{folder}'" if folder else ""
        return f"'{term}' appears 1 time in '{note['title']}'{loc}."

    if count_type == "notes":
        return f"{tc.note_count} notes mention '{term}'."

    return (
        f"'{term}' appears {tc.mention_count} time(s) "
        f"across {tc.note_count} note(s)."
    )


def _format_comparative(
    terms: list[str],
    results: dict[str, TermCount],
    count_type: str,
) -> str:
    ranked = sorted(terms, key=lambda t: results[t].mention_count, reverse=True)

    lines = []
    for t in ranked:
        tc = results[t]
        if tc.mention_count == 0:
            lines.append(f"'{t}': not found in any notes.")
        else:
            lines.append(
                f"'{t}': {tc.mention_count} mention(s) across {tc.note_count} note(s)."
            )

    return "\n".join(lines)


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

    matched: list[tuple[str, str, str, str]] = []
    for chunk in chunks:
        if pattern.search(chunk.text):
            note_id = chunk.metadata.get("note_id", "")
            note_title = chunk.metadata.get("note_title", "Untitled")
            folder = chunk.metadata.get("folder_title", "")
            folder_id = chunk.metadata.get("folder_id", "")
            if note_id and not any(m[0] == note_id for m in matched):
                matched.append((note_id, note_title, folder, folder_id))

    if not matched:
        return StrategyResult(
            fact=f'No — the term "{term}" does not appear in any of your notes.',
            skip_context=True,
        )

    citations = [
        {"note_id": nid, "title": title, "folder": folder, "folder_id": fid}
        for nid, title, folder, fid in matched
    ]

    if len(matched) == 1:
        nid, title, folder, _ = matched[0]
        location = f" (in {folder})" if folder else ""
        fact = f'Yes — found in "{title}"{location}.'
    else:
        lines = []
        for _, title, folder, _fid in matched:
            loc = f" (in {folder})" if folder else ""
            lines.append(f'- "{title}"{loc}')
        fact = f'Yes — found in {len(matched)} note(s):\n' + "\n".join(lines)

    return StrategyResult(
        fact=fact,
        source_ids=[m[0] for m in matched],
        skip_context=True,
        citations=citations,
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
