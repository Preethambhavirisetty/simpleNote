from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable



def _lines(text: str) -> list[str]:
    return text.splitlines()


def _stripped_lines(text: str) -> list[str]:
    return [l.strip() for l in _lines(text)]


def _non_empty_lines(text: str) -> list[str]:
    return [l for l in _stripped_lines(text) if l]


def _line_ratio(text: str, predicate: Callable[[str], bool]) -> float:
    lines = _non_empty_lines(text)
    if not lines:
        return 0.0
    return sum(1 for l in lines if predicate(l)) / len(lines)


def without_leading_heading(text: str) -> str:
    """Strip leading heading lines and return remaining body text."""
    lines = _lines(text)
    for i, line in enumerate(lines):
        if not re.match(r"^#{1,6}\s+\S", line.strip()):
            return "\n".join(lines[i:]).strip()
    return ""



def is_heading_only_type(text: str, body: str) -> bool:
    """All non-empty lines are heading markers with no body text."""
    lines = _non_empty_lines(text)
    if not lines:
        return False
    return all(re.match(r"^#{1,6}\s+\S", l) for l in lines)


def is_footer_type(text: str, body: str) -> bool:
    """
    Page markers, copyright, confidentiality notices, or repeated
    identical boilerplate lines with no informational value.
    """
    lines = _non_empty_lines(text)
    if not lines:
        return False

    FOOTER_PATTERNS = [
        r"^page\s+\d+\s+of\s+\d+$",
        r"^©\s*\d{4}",
        r"^\(c\)\s*\d{4}",
        r"confidential",
        r"internal use only",
        r"proprietary",
        r"^generated on\b",
        r"^prepared by\b",
        r"^review date\b",
        r"^all rights reserved",
        r"^for (compliance|legal) inquiries",
        r"^--- page break ---$",
    ]

    def is_footer_line(l: str) -> bool:
        low = l.lower()
        return any(re.search(p, low) for p in FOOTER_PATTERNS)

    # Any single line repeated 3+ times → footer
    counts = Counter(l.strip().lower() for l in lines)
    if any(v >= 3 for v in counts.values()):
        return True

    return _line_ratio(text, is_footer_line) >= 0.7


def is_fenced_json_type(text: str, body: str) -> bool:
    """Fenced ```json block."""
    stripped = text.strip()
    return bool(re.match(r"^```json(?:\s|$)", stripped, re.IGNORECASE))


def is_fenced_code_type(text: str, body: str) -> bool:
    """Fenced ``` or ~~~ block (non-JSON)."""
    stripped = text.strip()
    if re.match(r"^```json(?:\s|$)", stripped, re.IGNORECASE):
        return False
    return bool(re.match(r"^(`{3,}|~{3,})", stripped))


def is_json_type(text: str, body: str) -> bool:
    """
    Unfenced JSON object or array.
    Must start/end with braces and contain at least one quoted key.
    Avoids false positives on [Reserved for future use].
    """
    stripped = (body or text).strip()

    # Unwrap fenced json if somehow reaches here
    if re.match(r"^```json", stripped, re.IGNORECASE):
        stripped = re.sub(r"^```json\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"```\s*$", "", stripped).strip()

    if not (
        (stripped.startswith("{") and stripped.endswith("}")) or
        (stripped.startswith("[") and stripped.endswith("]"))
    ):
        return False

    has_kv = bool(re.search(r'"[^"]+"\s*:', stripped))
    has_quoted = bool(re.search(r'"[^"]+"', stripped))
    return has_kv or (has_quoted and len(stripped) > 10)


def is_raw_code_type(text: str, body: str) -> bool:
    """
    Unfenced command sequences or code blocks.
    Detects shell commands, Python, JS, SQL, Dockerfile etc.
    Requires at least 3 lines with 60%+ matching code patterns.
    """
    target = body if body else text

    SHELL_PREFIXES = (
        "python", "pip", "pip3", "npm", "npx", "yarn", "node",
        "docker", "docker-compose", "kubectl", "helm",
        "git", "curl", "wget", "cd ", "ls ", "mkdir", "rm ",
        "source ", "export ", "./", "bash ", "sh ", "chmod",
        "alembic", "uvicorn", "gunicorn", "celery", "airflow",
        "terraform", "ansible", "make ", "gradle", "mvn ",
    )

    CODE_PATTERNS = [
        re.compile(r"^\s*(def |class |import |from |return |async def )"),
        re.compile(r"^\s*(const |let |var |function |=>|async function )"),
        re.compile(r"^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER)\b", re.IGNORECASE),
        re.compile(r"^\s*[a-zA-Z_]\w*\s*=\s*.+"),
        re.compile(r"^\s*\{"),
        re.compile(r"^\s*(if|for|while|switch|try|catch)\s*[\(\{]"),
        re.compile(r"^(FROM|RUN|CMD|ENTRYPOINT|COPY|ENV|EXPOSE|WORKDIR|ARG|LABEL)\s"),
    ]

    lines = _non_empty_lines(target)
    if len(lines) < 3:
        return False

    def is_code_line(l: str) -> bool:
        l_low = l.strip().lower()
        if any(l_low.startswith(p.lower()) for p in SHELL_PREFIXES):
            return True
        return any(p.match(l) for p in CODE_PATTERNS)

    ratio = _line_ratio(target, is_code_line)
    return ratio >= 0.6


def is_table_type(text: str, body: str) -> bool:
    """
    Majority of non-empty lines are pipe-delimited rows.
    Works with or without markdown |---| separator.
    Requires at least 2 data rows.
    """
    target = body if body else text
    lines = _non_empty_lines(target)
    if len(lines) < 2:
        return False

    def is_table_row(l: str) -> bool:
        return l.count("|") >= 2

    data_rows = [
        l for l in lines
        if is_table_row(l) and not re.match(r"^[\|\s\-:]+$", l)
    ]
    return len(data_rows) >= 2 and _line_ratio(target, is_table_row) >= 0.6


def is_faq_type(text: str, body: str) -> bool:
    """
    One or more Q/A pairs.
    Q marker: Q: / Question: / Q.
    A marker: A: / Answer: / A.
    Keeps all pairs in one chunk regardless of answer length.
    """
    q_pattern = re.compile(r"^(Q[\.:]\s|Question[\.:]\s)", re.IGNORECASE)
    a_pattern = re.compile(r"^(A[\.:]\s|Answer[\.:]\s)", re.IGNORECASE)

    lines = _non_empty_lines(text)
    q_count = sum(1 for l in lines if q_pattern.match(l))
    a_count = sum(1 for l in lines if a_pattern.match(l))

    return q_count >= 1 and a_count >= 1 and abs(q_count - a_count) <= 1


def _speaker_label_followed_by_dialogue(lines: list[str], index: int) -> bool:
    for line in lines[index + 1:]:
        candidate = line.strip()
        if not candidate:
            continue
        if candidate.startswith("`") or re.match(
            r"^(?:[-*+]\s|\d+[.)]\s|#{1,6}\s|```|~~~)", candidate
        ):
            return False
        return not bool(re.match(r"^[A-Za-z][A-Za-z\s]{0,40}:\s+\S", candidate))
    return False


def is_transcript_type(text: str, body: str) -> bool:
    """
    Alternating speaker turns.
    Pattern A: Name:\ntext
    Pattern B: Name\nHH:MM AM/PM\ntext (chat paste)
    Pattern C: [HH:MM] Name:\ntext
    Requires 2+ distinct speakers.
    """
    lines = _lines(text)

    speaker_label = re.compile(r"^([A-Z][a-zA-Z\s]{1,30}):\s*$")
    chat_timestamp = re.compile(r"^\d{1,2}:\d{2}\s*(AM|PM)?$", re.IGNORECASE)
    ts_label = re.compile(r"^\[\d{2}:\d{2}(:\d{2})?\]\s+\w.*:\s*$")
    speakers_a: set[str] = set()
    speakers_b: set[str] = set()
    speakers_c: set[str] = set()

    for i, line in enumerate(lines):
        s = line.strip()
        if match := speaker_label.match(s):
            if _speaker_label_followed_by_dialogue(lines, i):
                speakers_a.add(match.group(1).strip().lower())
        if chat_timestamp.match(s) and i > 0:
            prev = lines[i - 1].strip()
            if re.match(r"^[A-Z][a-zA-Z\s]{1,30}$", prev):
                speakers_b.add(prev.lower())
        if ts_label.match(s):
            speakers_c.add(s.split("]")[1].strip().rstrip(":").lower())

    return (
        len(speakers_a) >= 2 or
        len(speakers_b) >= 2 or
        len(speakers_c) >= 2
    )


def is_glossary_type(text: str, body: str) -> bool:
    """
    Definition pairs: TERM: definition or TERM — definition.
    Majority of lines match a definition pattern.
    Excludes FAQ to avoid Q:/A: overlap.
    """
    if is_faq_type(text, body):
        return False

    lines = _non_empty_lines(text)
    if len(lines) < 2:
        return False

    def_pattern = re.compile(
        r"^([A-Z][A-Za-z0-9\s/\-]{0,40})\s*[:—–]\s*\S"
    )

    def is_def_line(l: str) -> bool:
        return bool(def_pattern.match(l))

    def is_continuation(l: str) -> bool:
        return l.startswith("  ") or l.startswith("\t")

    qualifying = sum(
        1 for l in lines
        if is_def_line(l) or is_continuation(l)
    )
    ratio = qualifying / len(lines)
    def_count = sum(1 for l in lines if is_def_line(l))
    return ratio >= 0.5 and def_count >= 2


def is_appendix_type(text: str, body: str) -> bool:
    """
    Appendix section: starts with an explicit appendix heading or marker.
    """
    lines = _non_empty_lines(text)
    if not lines:
        return False

    first_lines = lines[:3]
    appendix_heading = re.compile(
        r"^(?:#{1,6}\s+)?appendix(?:\s+[A-Z0-9]+)?(?:\s*[:—–-]|\b)",
        re.IGNORECASE,
    )
    return any(appendix_heading.match(line) for line in first_lines)


def is_quote_type(text: str, body: str) -> bool:
    """
    Quoted statements in double quotes or > blockquote syntax.
    Attribution lines (— Name) are part of the quote chunk.
    Requires at least one actual quote line.
    """
    lines = _non_empty_lines(body or text)
    if not lines:
        return False

    def is_quote_line(l: str) -> bool:
        return (
            (l.startswith('"') and l.endswith('"') and len(l) > 3) or
            (l.startswith("> ") or (l.startswith(">") and len(l) > 1))
        )

    def is_attribution_line(l: str) -> bool:
        return bool(re.match(r"^[—–\-]\s*\w", l))

    quote_lines = [l for l in lines if is_quote_line(l)]
    non_quote_non_attr = [
        l for l in lines
        if not is_quote_line(l) and not is_attribution_line(l)
    ]

    return len(quote_lines) >= 1 and len(non_quote_non_attr) == 0


def is_contact_type(text: str, body: str) -> bool:
    """
    STRICT: requires email address, phone number, or explicit label.
    Name alone, URL alone, identifiers, all-caps, address alone = NOT contact.
    """
    EMAIL = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
    PHONE = re.compile(
        r"(\+?\d[\d\s\-().]{7,}\d|"
        r"\(\d{3}\)\s*\d{3}[\-\s]\d{4}|"
        r"\d{3}[\-\s]\d{3}[\-\s]\d{4})"
    )
    LABEL = re.compile(
        r"^(email|phone|tel|fax|mobile|contact)\s*:",
        re.IGNORECASE
    )

    lines = _non_empty_lines(text)
    has_email = any(EMAIL.fullmatch(l) for l in lines)
    has_phone = any(PHONE.fullmatch(l.strip()) for l in lines)
    has_label = any(LABEL.match(l) for l in lines)

    return has_email or has_phone or has_label


def is_address_type(text: str, body: str) -> bool:
    """
    Physical mailing address without email/phone (those = contact).
    Requires 2+ address signals: street number, city/state/zip, postal code,
    building prefix. Supports international formats.
    """
    if is_contact_type(text, body):
        return False

    lines = _non_empty_lines(text)
    if not lines:
        return False

    STREET = re.compile(
        r"^\d+\s+[A-Z][a-zA-Z\s]+(Street|St|Avenue|Ave|Road|Rd|"
        r"Drive|Dr|Boulevard|Blvd|Lane|Ln|Way|Place|Pl|Court|Ct|"
        r"Parkway|Pkwy|Highway|Hwy|Straße|straße|strasse)\b",
        re.IGNORECASE
    )
    STREET_NUMBER_LAST = re.compile(
        r"^[A-Z][a-zA-Z\s]+(?:Straße|straße|strasse|Street|St|Road|Rd|Avenue|Ave)\s+\d+[A-Za-z]?\b",
        re.IGNORECASE
    )
    CITY_STATE_ZIP = re.compile(
        r"[A-Za-z\s]+,\s*[A-Z]{2}\s+\d{5}(-\d{4})?"
        r"|[A-Za-z\s]+,\s+[A-Za-z\s]+"
    )
    POSTAL = re.compile(
        r"\b\d{4,6}\b|"
        r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b"
    )
    BUILDING = re.compile(
        r"^(Building|Floor|Suite|Unit|Apt|Room|Block|P\.?O\.?\s*Box)\s",
        re.IGNORECASE
    )

    has_street = any(STREET.match(l) or STREET_NUMBER_LAST.match(l) for l in lines)
    has_city_state_zip = any(CITY_STATE_ZIP.fullmatch(l.strip()) for l in lines)
    has_postal_line = any(POSTAL.fullmatch(l.strip()) for l in lines)
    has_building = any(BUILDING.match(l) for l in lines)

    return has_street or has_city_state_zip or (has_postal_line and has_building)


def is_structured_list_type(text: str, body: str) -> bool:
    """
    Ordered list: arabic, hierarchical decimal, alphabetic, roman.
    Mixed formats in the same block → structured_list.
    """
    target = body if body else text
    lines = _non_empty_lines(target)
    if not lines:
        return False

    ORDERED_PATTERNS = [
        re.compile(r"^\d+\.\s+\S"),
        re.compile(r"^\d+\.\d+(\.\d+)?\s+\S"),
        re.compile(r"^[A-Z]\.\s+\S"),
        re.compile(r"^[A-Z]\)\s+\S"),
        re.compile(r"^\([ivxlcdmIVXLCDM]+\)\s+\S"),
        re.compile(r"^[ivxlcdm]+\.\s+\S"),
        re.compile(r"^[IVX]+\.\s+\S"),
    ]

    def is_ordered_line(l: str) -> bool:
        return any(p.match(l) for p in ORDERED_PATTERNS)

    ordered_count = sum(1 for l in lines if is_ordered_line(l))
    ratio = ordered_count / len(lines)
    return ordered_count >= 2 and ratio >= 0.4


def is_list_type(text: str, body: str) -> bool:
    """
    Unordered bullet list using -, *, + markers.
    Includes task lists [ ] / [x].
    Nested lists stay as one chunk.
    """
    target = body if body else text
    lines = _non_empty_lines(target)
    if not lines:
        return False

    bullet = re.compile(r"^\s*[-*+]\s+(\[[ xX]\]\s+)?.+")

    bullet_count = sum(1 for l in lines if bullet.match(l))
    ratio = bullet_count / len(lines)
    return bullet_count >= 2 and ratio >= 0.6


def starts_transcript_block(text: str) -> bool:
    lines = _lines(text)
    first_index = next((i for i, line in enumerate(lines) if line.strip()), None)
    if first_index is None:
        return False
    first_line = lines[first_index].strip()
    return bool(re.match(r"^[A-Z][a-zA-Z\s]{1,30}:\s*$", first_line)) and (
        _speaker_label_followed_by_dialogue(lines, first_index)
    )


def starts_glossary_block(text: str) -> bool:
    lines = _non_empty_lines(text)
    if not lines:
        return False
    term_pattern = re.compile(r"^[A-Z][A-Za-z0-9\s/-]{0,40}\s*[:\u2014\u2013]\s*\S")
    term_count = sum(1 for line in lines if term_pattern.match(line))
    return term_count >= 1 and term_count >= max(1, len(lines) - 1)


def continues_structured_list(previous: str, current: str) -> bool:
    combined = previous + chr(10) + current
    return is_structured_list_type(combined, combined)
