"""Lightweight PII detection and redaction (regex-based).

Used for two things:
  - scrubbing PII out of structured logs (always on), and
  - the notes.pii_egress_control flag, which blocks notes containing PII from being sent
    to the external LLM/embedding pipeline in the agent.

This is best-effort pattern matching, not a compliance-grade classifier.
"""

import re

_PATTERNS = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "phone": re.compile(r"\b\+?\d{1,3}[\s.-]?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}\b"),
}


def contains_pii(text: str | None) -> bool:
    if not text:
        return False
    return any(pattern.search(text) for pattern in _PATTERNS.values())


def redact(text: str | None) -> str | None:
    if not text:
        return text
    for name, pattern in _PATTERNS.items():
        text = pattern.sub(f"[REDACTED_{name.upper()}]", text)
    return text
