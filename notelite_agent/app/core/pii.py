"""Regex-based PII redaction for logs (mirrors the backend's app/core/pii.py).

Best-effort scrubbing so note-derived content never leaks into stdout/Loki during
ingestion or chat. Not a compliance-grade classifier.
"""

import re

_PATTERNS = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "phone": re.compile(r"\b\+?\d{1,3}[\s.-]?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}\b"),
}


def redact(text: str | None) -> str | None:
    if not text:
        return text
    for name, pattern in _PATTERNS.items():
        text = pattern.sub(f"[REDACTED_{name.upper()}]", text)
    return text
