"""Strategy executors for query plans.

Each strategy receives retrieved chunks (or all user chunks) and produces
an optional deterministic fact that gets injected into the LLM prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from llama_index.core import Document as LlamaDocument

from v2.notelite_agent._backup.handlers.strategies.keyword_count import KeywordCounter, KeywordExtractor, TermCount
from v2.notelite_agent._backup.pipeline.intent import QueryPlan


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


# Phrases like "list my travel notes" where ``KeywordExtractor`` may not fire.
_LISTING_TOPIC_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:^|\b)(?:list|show|give)\s+(?:me\s+)?(?:all\s+|every\s+)?(?:my\s+|the\s+)?"
        r"(?:notes?|entries?)\s+(?:about|on|for|regarding|related to|tagged|labeled)\s+"
        r"(.+?)[\s?.!]*$",
        re.I,
    ),
    re.compile(
        r"(?:^|\b)(?:all|every)\s+(?:my\s+)?(?:notes?|entries?)\s+"
        r"(?:about|on|for|regarding)\s+(.+?)[\s?.!]*$",
        re.I,
    ),
    re.compile(
        r"(?:^|\b)(?:list|show)\s+(?:all\s+)?(?:my|the)\s+(.+?)\s+notes?\b",
        re.I,
    ),
    re.compile(
        r"(?:^|\b)(?:everything|all)\s+(?:tagged|labeled)\s+(.+?)[\s?.!]*$",
        re.I,
    ),
)


def _resolve_listing_topic(plan: QueryPlan, query: str) -> str | None:
    """Topic for ``list_notes`` — plan fields, generic extract, then listing phrasing."""
    direct = _resolve_term(plan, query)
    if direct:
        return direct
    q = (query or "").strip()
    if not q:
        return None
    for rx in _LISTING_TOPIC_PATTERNS:
        m = rx.search(q)
        if not m:
            continue
        raw = m.group(1).strip()
        cleaned = KeywordExtractor._clean(raw)
        if cleaned:
            return cleaned
    return None


def _compile_term_pattern(term: str) -> re.Pattern[str]:
    t = term.strip()
    try:
        return re.compile(r"\b" + re.escape(t) + r"\b", re.IGNORECASE)
    except re.error:
        return re.compile(re.escape(t), re.IGNORECASE)


def _chunk_matches_term(chunk: LlamaDocument, pattern: re.Pattern[str]) -> bool:
    """Match title, folder, tags, and body (presence previously scanned body only)."""
    title = str(chunk.metadata.get("note_title", "") or "")
    folder = str(chunk.metadata.get("folder_title", "") or "")
    tags = str(chunk.metadata.get("tags", "") or "")
    hay = f"{title}\n{folder}\n{tags}\n{chunk.text}"
    return bool(pattern.search(hay))


def _parse_temporal_window(plan: QueryPlan, query: str) -> tuple[int, int] | None:
    """Return inclusive UTC (start_ts, end_ts) or None when no range is inferred."""
    parts: list[str] = []
    if query:
        parts.append(query.lower())
    if plan.slots:
        tr = plan.slots.get("time_range")
        if isinstance(tr, str) and tr.strip():
            parts.append(tr.lower())
    text = " ".join(parts)
    if not text.strip():
        return None

    now = datetime.now(timezone.utc)
    day_start = lambda d: int(  # noqa: E731
        datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()
    )

    m = re.search(r"\b(?:in the |over the )?last\s+(\d+)\s+days?\b", text)
    if not m:
        m = re.search(r"\bpast\s+(\d+)\s+days?\b", text)
    if m:
        n = min(int(m.group(1)), 3660)
        start_d = (now - timedelta(days=n)).date()
        return (day_start(start_d), int(now.timestamp()))

    if re.search(r"\byesterday\b", text):
        d = (now - timedelta(days=1)).date()
        s = day_start(d)
        return (s, s + 86400 - 1)

    if re.search(r"\btoday\b", text):
        s = day_start(now.date())
        return (s, int(now.timestamp()))

    if re.search(r"\b(?:last|past)\s+week\b", text):
        start_d = (now - timedelta(days=7)).date()
        return (day_start(start_d), int(now.timestamp()))

    if re.search(r"\bthis\s+week\b", text):
        mon = now.date() - timedelta(days=now.weekday())
        return (day_start(mon), int(now.timestamp()))

    if re.search(r"\b(?:last|past)\s+month\b", text):
        start_d = (now - timedelta(days=30)).date()
        return (day_start(start_d), int(now.timestamp()))

    if re.search(r"\b(?:last|past)\s+year\b", text):
        start_d = (now - timedelta(days=365)).date()
        return (day_start(start_d), int(now.timestamp()))

    return None


def _temporal_sort_ascending(query: str, window: tuple[int, int] | None) -> bool:
    """True = oldest → newest (timeline); False = newest first (recency / bounded slice)."""
    q = (query or "").lower()
    if any(
        x in q
        for x in (
            "chronological", "oldest first", "timeline", "from oldest",
            "in order of", "when did i first", "first note",
        )
    ):
        return True
    if any(
        x in q
        for x in (
            "latest", "most recent", "newest", "most recently",
            "just wrote", "last thing i wrote",
        )
    ):
        return False
    if window is not None:
        return False
    return True


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
    window = _parse_temporal_window(plan, query)
    entries: list[tuple[int, str, str]] = []
    for chunk in chunks:
        ts = chunk.metadata.get("created_at")
        if not ts:
            continue
        ts_i = int(ts)
        if window is not None:
            lo, hi = window
            if ts_i < lo or ts_i > hi:
                continue
        note_id = chunk.metadata.get("note_id", "")
        note_title = chunk.metadata.get("note_title", "Untitled")
        entries.append((ts_i, note_id, note_title))

    if not entries:
        if window is not None:
            return StrategyResult(
                fact="No notes with a known creation date fall in that time range.",
                skip_context=True,
            )
        return StrategyResult()

    entries.sort(key=lambda e: e[0])
    unique_notes: dict[str, tuple[int, str]] = {}
    for ts, nid, title in entries:
        if not nid:
            continue
        if nid not in unique_notes:
            unique_notes[nid] = (ts, title)

    ascending = _temporal_sort_ascending(query, window)
    ordered = sorted(
        unique_notes.items(),
        key=lambda x: x[1][0],
        reverse=not ascending,
    )

    lines: list[str] = []
    source_ids: list[str] = []
    for nid, (ts, title) in ordered:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%b %d, %Y")
        lines.append(f'- "{title}" on {dt}')
        source_ids.append(nid)

    if window is not None:
        header = (
            "Notes in the requested time range (oldest to newest)"
            if ascending
            else "Notes in the requested time range (newest first)"
        )
    elif ascending:
        header = "Matching notes in chronological order"
    else:
        header = "Matching notes (newest first)"
    fact = f"{header}:\n" + "\n".join(lines)
    return StrategyResult(fact=fact, source_ids=source_ids, skip_context=True)


# ── listing ───────────────────────────────────────────────────────────────

def _listing(plan: QueryPlan, chunks: list[LlamaDocument], query: str = "") -> StrategyResult:
    topic = _resolve_listing_topic(plan, query)
    pattern = _compile_term_pattern(topic) if topic else None

    seen: dict[str, tuple[str, str]] = {}
    for chunk in chunks:
        note_id = chunk.metadata.get("note_id", "")
        if not note_id:
            continue
        if pattern is not None and not _chunk_matches_term(chunk, pattern):
            continue
        title = chunk.metadata.get("note_title", "Untitled")
        folder = chunk.metadata.get("folder_title", "")
        if note_id not in seen:
            seen[note_id] = (title, folder)

    if not seen:
        if topic:
            return StrategyResult(
                fact=f'No notes match the topic "{topic}".',
                skip_context=True,
            )
        if not chunks:
            return StrategyResult()
        return StrategyResult(
            fact="No notes with identifiers were found to list.",
            skip_context=True,
        )

    lines = []
    for title, folder in seen.values():
        if folder:
            lines.append(f"- {title} (in {folder})")
        else:
            lines.append(f"- {title}")

    if topic:
        header = f'Found {len(seen)} note(s) matching "{topic}"'
    else:
        header = f"Found {len(seen)} note(s) in your collection"
    fact = f"{header}:\n" + "\n".join(lines)
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

    pattern = _compile_term_pattern(term)

    matched: list[tuple[str, str, str, str]] = []
    for chunk in chunks:
        if _chunk_matches_term(chunk, pattern):
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
