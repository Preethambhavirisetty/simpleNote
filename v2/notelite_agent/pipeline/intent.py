"""Hybrid query intent detection — regex fast-path + LLM fallback.

Classifies user queries into strategies (keyword_count, temporal, listing,
semantic) so the chat pipeline can execute deterministic logic before
handing off to the main LLM.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

import httpx
import structlog

from core.config import CHAT_LLM_API_BASE, LLM_API_KEY, INTENT_LLM_MAX_TOKENS

log = structlog.get_logger()

VALID_STRATEGIES = frozenset({"keyword_count", "temporal", "listing", "semantic"})

# ── Regex tier ────────────────────────────────────────────────────────────
# Each entry: (compiled_pattern, strategy, search_term_group_index_or_None)

_REGEX_RULES: list[tuple[re.Pattern, str, int | None]] = [
    (
        re.compile(
            r"how\s+many\s+times.*?"
            r"(?:say|said|mention(?:ed)?|wrote|write|use[ds]?|written|type[ds]?)"
            r"\s+['\"]?(.+?)['\"]?\s*\??$",
            re.IGNORECASE,
        ),
        "keyword_count",
        1,
    ),
    (
        re.compile(
            r"(?:count|total\s+number\s+of)\s+.*?['\"](.+?)['\"]",
            re.IGNORECASE,
        ),
        "keyword_count",
        1,
    ),
    (
        re.compile(
            r"when\s+did\s+(?:i|we)\s+.*?"
            r"(?:say|said|mention|write|wrote|add|added|note|create)",
            re.IGNORECASE,
        ),
        "temporal",
        None,
    ),
    (
        re.compile(
            r"(?:list\s+all|show\s+(?:me\s+)?all|what\s+are\s+all)\b",
            re.IGNORECASE,
        ),
        "listing",
        None,
    ),
]

# ── LLM planner prompt ───────────────────────────────────────────────────

_PLANNER_SYSTEM_PROMPT = """\
You are a query classifier. Given a user question about their personal notes, \
output a JSON object with two fields:
  "strategy": one of "keyword_count", "temporal", "listing", "semantic"
  "search_term": the exact phrase to search for (only for keyword_count), or null

Strategy definitions:
- keyword_count: user wants an exact count of how many times a word or phrase \
appears (e.g. "how many times did I say X", "count occurrences of X").
- temporal: user wants to know *when* something happened or was written \
(e.g. "when did I mention coffee?", "what date did I write about the meeting?").
- listing: user wants a list or enumeration of items from their notes \
(e.g. "list all my notes about travel", "show me everything about recipes").
- semantic: any other question that requires understanding and reasoning \
over the note content. This is the default.

Output ONLY valid JSON, nothing else."""


@dataclass
class QueryPlan:
    strategy: str
    search_term: str | None = None
    confidence: float = 1.0
    source: str = "regex"


class QueryPlanner:
    """Two-tier intent classifier: regex rules first, LLM fallback second."""

    def plan(self, query: str) -> QueryPlan:
        plan = self._try_regex(query)
        if plan is not None:
            return plan
        return self._try_llm(query)

    @staticmethod
    def _try_regex(query: str) -> QueryPlan | None:
        for pattern, strategy, group_idx in _REGEX_RULES:
            m = pattern.search(query)
            if m:
                search_term = m.group(group_idx).strip() if group_idx is not None else None
                return QueryPlan(
                    strategy=strategy,
                    search_term=search_term,
                    confidence=1.0,
                    source="regex",
                )
        return None

    @staticmethod
    def _try_llm(query: str) -> QueryPlan:
        t0 = time.monotonic()
        try:
            resp = httpx.post(
                f"{CHAT_LLM_API_BASE}/chat/completions",
                headers={"Authorization": f"Bearer {LLM_API_KEY}"},
                json={
                    "model": "llama3.1",
                    "messages": [
                        {"role": "system", "content": _PLANNER_SYSTEM_PROMPT},
                        {"role": "user", "content": query},
                    ],
                    "max_tokens": INTENT_LLM_MAX_TOKENS,
                    "temperature": 0.0,
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip()
            parsed = json.loads(raw)

            strategy = parsed.get("strategy", "semantic")
            if strategy not in VALID_STRATEGIES:
                strategy = "semantic"

            search_term = parsed.get("search_term")

            latency_ms = int((time.monotonic() - t0) * 1000)
            log.info(
                "intent.llm_plan",
                query=query,
                strategy=strategy,
                search_term=search_term,
                latency_ms=latency_ms,
            )
            return QueryPlan(
                strategy=strategy,
                search_term=search_term,
                confidence=0.8,
                source="llm",
            )
        except Exception:
            latency_ms = int((time.monotonic() - t0) * 1000)
            log.warning("intent.llm_fallback", query=query, latency_ms=latency_ms, exc_info=True)
            return QueryPlan(strategy="semantic", confidence=0.0, source="llm")
