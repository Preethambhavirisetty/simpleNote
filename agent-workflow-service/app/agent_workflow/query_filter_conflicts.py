"""Detect site/lab filter conflicts from the user query before MCP expansion."""

from __future__ import annotations

import re

from app.agent_workflow.site_labs_mapping import lab_belongs_to_site, site_for_lab

_SITE_EQ_RE = re.compile(r"\bsite\s*=\s*([A-Za-z0-9_/-]+)", re.IGNORECASE)
_SITE_PHRASE_RE = re.compile(
    r"\b(?:at|for|in|on)\s+(?:the\s+)?([A-Z]{2,6}(?:/[A-Z]{2,6})?)\s+(?:site|region)\b",
    re.IGNORECASE,
)
_LAB_TOKEN_RE = re.compile(r"\b(?:lab|labs)\s+([A-Za-z0-9_./()-]+)\b", re.IGNORECASE)
_LAB_CODE_RE = re.compile(r"\b([A-Z]{2,6}\d{2}-[A-Z0-9./()+-]+)\b")


def _normalize_site(value: str) -> str:
    return str(value or "").strip().upper()


def _normalize_lab(value: str) -> str:
    text = str(value or "").strip().strip("\"'")
    if text.endswith("*"):
        text = text[:-1]
    return text


def extract_site_from_query(query: str) -> str | None:
    text = str(query or "")
    match = _SITE_EQ_RE.search(text)
    if match:
        site = _normalize_site(match.group(1))
        return site or None
    match = _SITE_PHRASE_RE.search(text)
    if match:
        site = _normalize_site(match.group(1))
        return site or None
    return None


def extract_lab_from_query(query: str) -> str | None:
    text = str(query or "")
    match = _LAB_TOKEN_RE.search(text)
    if match:
        lab = _normalize_lab(match.group(1))
        if lab and lab.upper() not in {"ROW", "ROWS", "SITE", "POWER"}:
            return lab
    for match in _LAB_CODE_RE.finditer(text):
        lab = _normalize_lab(match.group(1))
        if lab:
            return lab
    return None


def query_filter_conflict_gaps(user_query: str) -> list[str]:
    """Return conflicts when the query names a site and lab that do not align."""
    site = extract_site_from_query(user_query)
    lab = extract_lab_from_query(user_query)
    if not site or not lab:
        return []
    if lab_belongs_to_site(lab, site):
        return []
    mapped_site = site_for_lab(lab)
    if mapped_site and mapped_site != site:
        return [
            f"site={site!r} conflicts with labs={lab!r} (lab maps to site={mapped_site!r})."
        ]
    return [f"site={site!r} may not include labs={lab!r} per sites-labs-mapping."]
