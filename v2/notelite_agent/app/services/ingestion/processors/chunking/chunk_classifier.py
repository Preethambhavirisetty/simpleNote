import re

from app.services.ingestion.processors.chunking.chunk_types import classify_chunk_type

# from typing import Optional


# # ---------------------------------------------------------------------------
# # Utility helpers
# # ---------------------------------------------------------------------------

# def _lines(text: str) -> list[str]:
#     return text.splitlines()


# def _stripped_lines(text: str) -> list[str]:
#     return [l.strip() for l in _lines(text)]


# def _non_empty_lines(text: str) -> list[str]:
#     return [l for l in _stripped_lines(text) if l]


# def _line_ratio(text: str, predicate) -> float:
#     lines = _non_empty_lines(text)
#     if not lines:
#         return 0.0
#     return sum(1 for l in lines if predicate(l)) / len(lines)


# # ---------------------------------------------------------------------------
# # Individual type detectors
# # Returns True if the text matches the type, False otherwise.
# # Order of calling matters — see classify() at the bottom.
# # ---------------------------------------------------------------------------


# def is_heading_only(text: str) -> bool:
#     """
#     All non-empty lines are heading markers (# H1–H6).
#     No body text exists beneath any heading.
#     """
#     lines = _non_empty_lines(text)
#     if not lines:
#         return False
#     return all(re.match(r"^#{1,6}\s+\S", l) for l in lines)


# def is_footer(text: str) -> bool:
#     """
#     Content consists of page markers, copyright, confidentiality notices,
#     or repeated identical lines with no informational value.

#     Signals:
#     - Line matches page marker:  Page X of Y
#     - Line matches copyright:    © YEAR or (c) YEAR
#     - Line contains CONFIDENTIAL / INTERNAL USE ONLY / PROPRIETARY
#     - Any line repeated 3+ times across the chunk
#     - Generated on / Prepared by / Review Date with no other content
#     """
#     lines = _non_empty_lines(text)
#     if not lines:
#         return False

#     FOOTER_PATTERNS = [
#         r"^page\s+\d+\s+of\s+\d+$",
#         r"^©\s*\d{4}",
#         r"^\(c\)\s*\d{4}",
#         r"confidential",
#         r"internal use only",
#         r"proprietary",
#         r"^generated on\b",
#         r"^prepared by\b",
#         r"^review date\b",
#         r"^all rights reserved",
#         r"^for (compliance|legal) inquiries",
#     ]

#     def is_footer_line(l: str) -> bool:
#         low = l.lower()
#         return any(re.search(p, low) for p in FOOTER_PATTERNS)

#     # Any line repeated 3+ times
#     from collections import Counter
#     counts = Counter(l.strip().lower() for l in lines)
#     has_repeat = any(v >= 3 for v in counts.values())
#     if has_repeat:
#         return True

#     # Majority of lines are footer signals
#     ratio = _line_ratio(text, is_footer_line)
#     return ratio >= 0.7


# def is_table(text: str) -> bool:
#     """
#     Majority of non-empty lines are pipe-delimited rows.
#     Works with or without markdown separator row (|---|).
#     Requires at least 2 rows to avoid false positives on single pipes.
#     """
#     lines = _non_empty_lines(text)
#     if len(lines) < 2:
#         return False

#     def is_table_row(l: str) -> bool:
#         # Must have at least 2 pipe characters
#         return l.count("|") >= 2

#     pipe_lines = [l for l in lines if is_table_row(l)]
#     # Separator-only lines like |---|---| should not count as data rows
#     data_rows = [
#         l for l in pipe_lines
#         if not re.match(r"^[\|\s\-:]+$", l)
#     ]
#     return len(data_rows) >= 2 and _line_ratio(text, is_table_row) >= 0.6


# def is_code(text: str) -> bool:
#     """
#     Fenced code blocks (``` or ~~~) or unfenced command sequences.

#     Fenced: starts with ``` or ~~~ optionally followed by a language tag.
#     Unfenced: majority of lines match shell/code patterns.
#     """
#     stripped = text.strip()

#     # Fenced detection
#     if re.match(r"^(`{3}|~{3})", stripped):
#         return True

#     # Unfenced command sequence detection
#     SHELL_PREFIXES = (
#         "python", "pip", "pip3", "npm", "npx", "yarn", "node",
#         "docker", "docker-compose", "kubectl", "helm",
#         "git", "curl", "wget", "cd ", "ls ", "mkdir", "rm ",
#         "source ", "export ", "./", "bash ", "sh ", "chmod",
#         "alembic", "uvicorn", "gunicorn", "celery", "airflow",
#         "terraform", "ansible", "make ", "gradle", "mvn ",
#     )

#     CODE_PATTERNS = [
#         r"^\s*(def |class |import |from |return |async def )",  # Python
#         r"^\s*(const |let |var |function |=>|async function )",  # JS/TS
#         r"^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER)\b",  # SQL
#         r"^\s*[a-zA-Z_]\w*\s*=\s*.+",  # assignment
#         r"^\s*\{",  # opening brace
#         r"^\s*(if|for|while|switch|try|catch)\s*[\(\{]",  # control flow
#         r"^\s*#\s*(Build|Run|Install|Configure|Stage)\b",  # Dockerfile comment
#         r"^(FROM|RUN|CMD|ENTRYPOINT|COPY|ENV|EXPOSE|WORKDIR|ARG|LABEL)\s",  # Dockerfile
#     ]

#     lines = _non_empty_lines(text)
#     if not lines:
#         return False

#     def is_code_line(l: str) -> bool:
#         l_stripped = l.strip().lower()
#         if any(l_stripped.startswith(p.lower()) for p in SHELL_PREFIXES):
#             return True
#         return any(re.match(p, l, re.IGNORECASE) for p in CODE_PATTERNS)

#     ratio = _line_ratio(text, is_code_line)
#     # Require strong signal for unfenced: at least 3 lines and 60% match
#     return len(lines) >= 3 and ratio >= 0.6


# def is_json(text: str) -> bool:
#     """
#     Valid or near-valid JSON structure.
#     Starts with { or [ and ends with } or ].
#     Must contain at least one quoted key or colon pair to avoid
#     false-positiving on [Reserved for future use] etc.

#     Also detects JSON inside a fenced ```json block.
#     """
#     stripped = text.strip()

#     # Unwrap fenced json block
#     if re.match(r"^```json", stripped, re.IGNORECASE):
#         inner = re.sub(r"^```json\s*", "", stripped, flags=re.IGNORECASE)
#         inner = re.sub(r"```\s*$", "", inner).strip()
#         stripped = inner

#     if not ((stripped.startswith("{") and stripped.endswith("}")) or
#             (stripped.startswith("[") and stripped.endswith("]"))):
#         return False

#     # Must have at least one "key": value pair or quoted string
#     has_kv = bool(re.search(r'"[^"]+"\s*:', stripped))
#     has_quoted = bool(re.search(r'"[^"]+"', stripped))
#     return has_kv or (has_quoted and len(stripped) > 10)


# def is_faq(text: str) -> bool:
#     """
#     Contains one or more Q/A pairs.
#     Q marker: line starting with Q: / Question: / Q.
#     A marker: line starting with A: / Answer: / A.
#     Both markers must be present. Ratio-based to handle mixed content.
#     """
#     q_pattern = re.compile(r"^(Q[\.:]\s|Question[\.:]\s)", re.IGNORECASE)
#     a_pattern = re.compile(r"^(A[\.:]\s|Answer[\.:]\s)", re.IGNORECASE)

#     lines = _non_empty_lines(text)
#     q_count = sum(1 for l in lines if q_pattern.match(l))
#     a_count = sum(1 for l in lines if a_pattern.match(l))

#     # Need at least one complete Q/A pair
#     return q_count >= 1 and a_count >= 1 and abs(q_count - a_count) <= 1


# def is_transcript(text: str) -> bool:
#     """
#     Alternating speaker turns.

#     Pattern A — Name label:  "John:\ntext" or "John:\n\ntext"
#     Pattern B — Chat format: "Name\nHH:MM AM/PM\n\ntext"
#     Pattern C — Timestamped: "[HH:MM] Name:\ntext"

#     Requires at least 2 distinct speakers to avoid false positives
#     on bullet lists that happen to have colons.
#     """
#     lines = _lines(text)

#     # Pattern A: lines matching "Word(s):\n" where the name is 1–4 words
#     speaker_label = re.compile(r"^([A-Z][a-zA-Z\s]{1,30}):\s*$")
#     # Pattern B: chat timestamp after a name
#     chat_timestamp = re.compile(r"^\d{1,2}:\d{2}\s*(AM|PM)?$", re.IGNORECASE)
#     # Pattern C: [HH:MM] Name:
#     ts_label = re.compile(r"^\[\d{2}:\d{2}(:\d{2})?\]\s+\w.*:\s*$")

#     speakers_a: set[str] = set()
#     speakers_b: set[str] = set()
#     speakers_c: set[str] = set()

#     for i, line in enumerate(lines):
#         s = line.strip()
#         if speaker_label.match(s):
#             speakers_a.add(s.rstrip(":").strip().lower())
#         if chat_timestamp.match(s) and i > 0:
#             prev = lines[i - 1].strip()
#             if re.match(r"^[A-Z][a-zA-Z\s]{1,30}$", prev):
#                 speakers_b.add(prev.lower())
#         if ts_label.match(s):
#             speakers_c.add(s.split("]")[1].strip().rstrip(":").lower())

#     return (
#         len(speakers_a) >= 2 or
#         len(speakers_b) >= 2 or
#         len(speakers_c) >= 2
#     )


# def is_quote(text: str) -> bool:
#     """
#     One or more quoted statements.

#     Signals:
#     - Lines wrapped in double quotes: "..."
#     - Lines starting with > (markdown blockquote)
#     - Attribution lines (— Name) count as part of the quote chunk,
#       not as disqualifying noise.

#     Require at least one actual quote line; attribution alone is not enough.
#     """
#     lines = _non_empty_lines(text)
#     if not lines:
#         return False

#     def is_quote_line(l: str) -> bool:
#         return (
#             (l.startswith('"') and l.endswith('"') and len(l) > 3) or
#             l.startswith("> ") or
#             l.startswith(">") and len(l) > 1
#         )

#     def is_attribution_line(l: str) -> bool:
#         return bool(re.match(r"^[—–-]\s*\w", l))

#     quote_lines = [l for l in lines if is_quote_line(l)]
#     non_quote_non_attr = [
#         l for l in lines
#         if not is_quote_line(l) and not is_attribution_line(l)
#     ]

#     return len(quote_lines) >= 1 and len(non_quote_non_attr) == 0


# def is_glossary(text: str) -> bool:
#     """
#     Definition pairs: TERM: definition or TERM — definition.

#     Formats:
#     - TERM: definition (colon separator)
#     - TERM — definition (em dash separator)
#     - TERM – definition (en dash separator)
#     - ACRONYM: expanded form (short term, longer value)

#     Require majority of non-empty lines to match a definition pattern.
#     Exclude FAQ (Q:/A: format) to avoid overlap.
#     """
#     if is_faq(text):
#         return False

#     lines = _non_empty_lines(text)
#     if len(lines) < 2:
#         return False

#     # Definition line: starts with a term (1-6 words, possibly all-caps)
#     # followed by : or — or –
#     def_pattern = re.compile(
#         r"^([A-Z][A-Za-z0-9\s/\-]{0,40})\s*[:—–]\s*\S"
#     )

#     def is_def_line(l: str) -> bool:
#         return bool(def_pattern.match(l))

#     # Continuation lines (indented definitions) are acceptable
#     def is_continuation(l: str) -> bool:
#         return l.startswith("  ") or l.startswith("\t")

#     qualifying = sum(
#         1 for l in lines
#         if is_def_line(l) or is_continuation(l)
#     )
#     ratio = qualifying / len(lines)
#     return ratio >= 0.5 and sum(1 for l in lines if is_def_line(l)) >= 2


# def is_contact(text: str) -> bool:
#     """
#     STRICT: requires at least one of:
#     - Email address pattern (x@x.x)
#     - Phone number pattern
#     - Explicit label: Email: / Phone: / Tel: / Fax:

#     A name alone, URL alone, identifiers alone, all-caps text alone,
#     or address alone do NOT qualify as contact.
#     """
#     EMAIL = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
#     PHONE = re.compile(
#         r"(\+?\d[\d\s\-().]{7,}\d|"        # international
#         r"\(\d{3}\)\s*\d{3}[\-\s]\d{4}|"   # US (xxx) xxx-xxxx
#         r"\d{3}[\-\s]\d{3}[\-\s]\d{4})"    # US xxx-xxx-xxxx
#     )
#     LABEL = re.compile(
#         r"^(email|phone|tel|fax|mobile|contact)\s*:",
#         re.IGNORECASE
#     )

#     lines = _non_empty_lines(text)
#     has_email = any(EMAIL.search(l) for l in lines)
#     has_phone = any(PHONE.search(l) for l in lines)
#     has_label = any(LABEL.match(l) for l in lines)

#     return has_email or has_phone or has_label


# def is_address(text: str) -> bool:
#     """
#     Physical mailing address.

#     Must NOT already qualify as contact (no email/phone).
#     Signals:
#     - Line with street number + street name: 123 Main Street
#     - Line with city + state/country pattern
#     - Postal/zip code on its own line or inline
#     - Building/Suite/Floor prefix lines

#     International formats supported (German, UK, Singapore etc.)
#     Require at least 2 address signals to confirm.
#     """
#     # If it has email or phone, classify as contact instead
#     if is_contact(text):
#         return False

#     lines = _non_empty_lines(text)
#     if not lines:
#         return False

#     STREET = re.compile(
#         r"^\d+\s+[A-Z][a-zA-Z\s]+(Street|St|Avenue|Ave|Road|Rd|"
#         r"Drive|Dr|Boulevard|Blvd|Lane|Ln|Way|Place|Pl|Court|Ct|"
#         r"Parkway|Pkwy|Highway|Hwy|Straße|straße|strasse)\b",
#         re.IGNORECASE
#     )
#     CITY_STATE_ZIP = re.compile(
#         r"[A-Za-z\s]+,\s*[A-Z]{2}\s+\d{5}(-\d{4})?"  # US: City, ST 12345
#         r"|[A-Za-z\s]+,\s+[A-Za-z\s]+"                # International: City, Country
#     )
#     POSTAL = re.compile(
#         r"\b\d{4,6}\b|"          # generic postal code
#         r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b"  # UK postcode
#     )
#     BUILDING = re.compile(
#         r"^(Building|Floor|Suite|Unit|Apt|Room|Block|P\.?O\.?\s*Box)\s",
#         re.IGNORECASE
#     )

#     signals = 0
#     for l in lines:
#         if STREET.match(l): signals += 2
#         if CITY_STATE_ZIP.search(l): signals += 2
#         if POSTAL.search(l): signals += 1
#         if BUILDING.match(l): signals += 1

#     return signals >= 2


# def is_list(text: str) -> bool:
#     """
#     Unordered bullet list using -, *, or + markers.
#     Also task lists with [ ] / [x] markers.
#     Nested lists (indented) stay as one chunk.
#     Require majority of non-empty lines to be bullet lines.
#     """
#     lines = _non_empty_lines(text)
#     if not lines:
#         return False

#     bullet = re.compile(r"^\s*[-*+]\s+(\[[ xX]\]\s+)?.+")

#     ratio = _line_ratio(text, lambda l: bool(bullet.match(l)))
#     bullet_count = sum(1 for l in lines if bullet.match(l))
#     return bullet_count >= 2 and ratio >= 0.6


# def is_structured_list(text: str) -> bool:
#     """
#     Ordered list with explicit markers:
#     - Arabic: 1. 2. 3.
#     - Hierarchical decimal: 1.1 1.2 2.1
#     - Alphabetic: A. B. C. or A) B) C)
#     - Roman: i. ii. iii. or I. II. III. or (i) (ii)
#     Mixed formats in the same block → still structured_list.
#     Must NOT overlap with list (no unordered bullets).
#     """
#     lines = _non_empty_lines(text)
#     if not lines:
#         return False

#     ORDERED_PATTERNS = [
#         re.compile(r"^\d+\.\s+\S"),                    # 1. Item
#         re.compile(r"^\d+\.\d+(\.\d+)?\s+\S"),         # 1.1 SubItem
#         re.compile(r"^[A-Z]\.\s+\S"),                  # A. Item
#         re.compile(r"^[A-Z]\)\s+\S"),                  # A) Item
#         re.compile(r"^\([ivxlcdmIVXLCDM]+\)\s+\S"),    # (i) Item
#         re.compile(r"^[ivxlcdmIVXLCDM]+\.\s+\S"),      # i. Item
#         re.compile(r"^[IVX]+\.\s+\S"),                 # I. Item
#     ]

#     def is_ordered_line(l: str) -> bool:
#         return any(p.match(l) for p in ORDERED_PATTERNS)

#     ordered_count = sum(1 for l in lines if is_ordered_line(l))
#     ratio = ordered_count / len(lines)
#     return ordered_count >= 2 and ratio >= 0.4


# # ---------------------------------------------------------------------------
# # Master classifier
# # ---------------------------------------------------------------------------

def classify_chunk(text: str) -> str:
    """
    Classify a chunk of text into one of the defined chunk types.

    Evaluation order matters:
    1. Structural/format types checked first (high specificity)
    2. Contact before address (address excludes contact internally)
    3. Ambiguous types (glossary, list) checked before content
    4. content is the default fallback
    """
    return classify_chunk_type(text).value


# # ---------------------------------------------------------------------------
# # Boundary splitter
# # Decides where to insert chunk boundaries in a full document.
# # Returns a list of (text, chunk_type) tuples.
# # ---------------------------------------------------------------------------

def split_into_typed_chunks(text: str) -> list[tuple[str, str]]:
    """Split a document on structural boundaries, then classify each block."""
    clean = text.strip()
    if not clean:
        return []

    whole_type = classify_chunk(clean)
    atomic_types = {
        "address", "contact", "faq", "glossary", "json", "list", "quote",
        "structured_list",
    }
    if whole_type in atomic_types:
        return [(clean, whole_type)]
    if whole_type == "content" and not re.search(r"^#{1,6}\s+\S", clean, re.MULTILINE):
        paragraph_types = [classify_chunk(block) for kind, block in _structural_blocks(clean) if kind == "prose"]
        has_structural_blocks = any(kind in {"code", "json", "table", "footer"} for kind, _ in _structural_blocks(clean))
        if not has_structural_blocks and "code" not in paragraph_types:
            return [(clean, whole_type)]
    if whole_type in {"footer", "heading_only", "transcript"} and "```" not in clean and "~~~" not in clean:
        return [(clean, whole_type)]
    if whole_type in {"code", "table"} and "\n\n" not in clean:
        return [(clean, whole_type)]

    blocks = _structural_blocks(clean)
    chunks: list[tuple[str, str]] = []
    headings: list[str] = []
    footer_lines: list[str] = []
    after_footer = False

    def emit(content: str, chunk_type: str | None = None) -> None:
        value = content.strip()
        if not value:
            return
        kind = chunk_type or classify_chunk(value)
        if chunks and kind == "content" and chunks[-1][1] == "content" and not _starts_markdown_heading(value):
            previous, _ = chunks[-1]
            chunks[-1] = (f"{previous}\n\n{value}", kind)
        else:
            chunks.append((value, kind))

    for block_kind, block in blocks:
        if block_kind == "heading":
            depth = _heading_depth(block)
            if headings and depth <= _heading_depth(headings[-1]):
                emit("\n\n".join(headings), "heading_only")
                headings = headings[: max(0, depth - 1)]
            headings.append(block)
            continue

        if block_kind == "footer":
            footer_lines.append(block)
            after_footer = True
            continue

        if block_kind in {"table", "code", "json"}:
            if headings and not chunks:
                emit("\n\n".join(headings), "heading_only")
            elif headings:
                block = f"{'\n\n'.join(headings)}\n\n{block}".strip()
            headings.clear()
            emit(block, block_kind)
            continue

        kind = "transcript" if _looks_like_narrative_dialogue(block) else classify_chunk(block)
        if headings:
            block = f"{'\n\n'.join(headings)}\n\n{block}".strip()
            headings = []
            kind = "transcript" if _looks_like_narrative_dialogue(block) else classify_chunk(block)

        if after_footer and kind == "content" and chunks and chunks[-1][1] == "content":
            chunks.append((block.strip(), kind))
        else:
            emit(block, kind)

    if headings:
        emit("\n\n".join(headings), "heading_only")

    if footer_lines:
        footer = "\n".join(footer_lines)
        page_markers = sum(1 for line in footer_lines if re.search(r"\bpage\s+\d+\s+of\s+\d+\b", line, re.IGNORECASE))
        content_indexes = [index for index, (_, kind) in enumerate(chunks) if kind == "content"]
        indexes_to_merge = content_indexes if page_markers <= 1 else content_indexes[1:]
        if len(indexes_to_merge) > 1:
            first = indexes_to_merge[0]
            merged_content = "\n\n".join(chunks[index][0] for index in indexes_to_merge)
            chunks = [item for index, item in enumerate(chunks) if index not in indexes_to_merge]
            chunks.insert(min(first, len(chunks)), (merged_content, "content"))
        insert_at = 1 if chunks and chunks[0][1] == "content" else 0
        chunks.insert(insert_at, (footer, "footer"))

    chunks = _merge_dialogue_chunks(chunks, whole_type == "transcript")
    chunks = _merge_same_type_lists(chunks)
    if not any(kind in {"code", "json", "table"} for _, kind in chunks) and any(kind in {"list", "structured_list", "transcript"} for _, kind in chunks):
        chunks = _merge_content_chunks(chunks)
    return _merge_heading_only_runs(chunks)


def _structural_blocks(text: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    paragraph: list[str] = []
    fenced: list[str] = []
    table: list[str] = []
    in_fence = False
    fence_char = ""

    def flush_paragraph() -> None:
        value = "\n".join(paragraph).strip()
        if value:
            blocks.append(("prose", value))
        paragraph.clear()

    def flush_table() -> None:
        value = "\n".join(table).strip()
        if value:
            blocks.append(("table", value))
        table.clear()

    for line in text.splitlines():
        stripped = line.strip()
        if in_fence:
            fenced.append(line)
            if re.fullmatch(rf"{re.escape(fence_char)}{{3,}}\s*", stripped):
                value = "\n".join(fenced).strip()
                kind = "json" if re.match(r"^```json(?:\s|$)", value, re.IGNORECASE) else "code"
                blocks.append((kind, value))
                fenced.clear()
                in_fence = False
            continue

        if re.match(r"^(`{3,}|~{3,})", stripped):
            flush_paragraph()
            flush_table()
            in_fence = True
            fence_char = stripped[0]
            fenced.append(line)
            continue

        if _is_footer_line(stripped):
            flush_paragraph()
            flush_table()
            blocks.append(("footer", stripped))
            continue

        if re.match(r"^#{1,6}\s+\S", stripped):
            flush_paragraph()
            flush_table()
            blocks.append(("heading", stripped))
            continue

        is_table_row = stripped.count("|") >= 2
        if is_table_row:
            flush_paragraph()
            table.append(line)
            continue
        if table and stripped:
            flush_table()

        if not stripped:
            flush_paragraph()
            flush_table()
        else:
            paragraph.append(line)

    flush_paragraph()
    flush_table()
    if fenced:
        blocks.append(("code", "\n".join(fenced).strip()))
    return blocks



def _looks_like_narrative_dialogue(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 3 or not lines[0].endswith(":"):
        return False
    if any(re.match(r"^[-*+]\s+", line) for line in lines[1:]):
        return False
    return sum(1 for line in lines[1:] if re.match(r"^[A-Z][A-Za-z'’-]+\s+\S", line)) >= 2

def _is_footer_line(line: str) -> bool:
    return bool(line and re.search(
        r"(^page\s+\d+\s+of\s+\d+$|confidential|internal use only|---\s*page break\s*---|©\s*\d{4}|all rights reserved)",
        line,
        re.IGNORECASE,
    ))


def _heading_depth(heading: str) -> int:
    return len(heading) - len(heading.lstrip("#"))


def _starts_markdown_heading(text: str) -> bool:
    return bool(re.match(r"^#{1,6}\s+\S", text.strip()))


def _merge_dialogue_chunks(
    chunks: list[tuple[str, str]], is_transcript_document: bool
) -> list[tuple[str, str]]:
    if not is_transcript_document:
        return chunks
    dialogue_indexes = [
        index for index, (content, kind) in enumerate(chunks)
        if kind == "transcript" or re.match(r"^(?:\[\d{2}:\d{2}(?::\d{2})?\]\s+)?[A-Z][^\n:]{0,60}:\s*$", content.splitlines()[0].strip())
    ]
    if len(dialogue_indexes) < 2:
        return chunks
    first = dialogue_indexes[0]
    dialogue = "\n\n".join(chunks[index][0] for index in dialogue_indexes)
    output = [item for index, item in enumerate(chunks) if index not in dialogue_indexes]
    output.insert(min(first, len(output)), (dialogue, "transcript"))
    return output


def _merge_same_type_lists(chunks: list[tuple[str, str]]) -> list[tuple[str, str]]:
    list_indexes = [index for index, (_, kind) in enumerate(chunks) if kind in {"list", "structured_list"}]
    if len(list_indexes) < 2:
        return chunks
    first = list_indexes[0]
    merged = "\n\n".join(chunks[index][0] for index in list_indexes)
    output = [item for index, item in enumerate(chunks) if index not in list_indexes]
    output.insert(min(first, len(output)), (merged, chunks[first][1]))
    return output



def _merge_content_chunks(chunks: list[tuple[str, str]]) -> list[tuple[str, str]]:
    indexes = [index for index, (_, kind) in enumerate(chunks) if kind == "content"]
    if len(indexes) < 2:
        return chunks
    first = indexes[0]
    merged = "\n\n".join(chunks[index][0] for index in indexes)
    output = [item for index, item in enumerate(chunks) if index not in indexes]
    output.insert(min(first, len(output)), (merged, "content"))
    return output

def _merge_heading_only_runs(chunks: list[tuple[str, str]]) -> list[tuple[str, str]]:
    output: list[tuple[str, str]] = []
    for content, kind in chunks:
        if output and kind == "heading_only" and output[-1][1] == "heading_only":
            output[-1] = (f"{output[-1][0]}\n\n{content}", kind)
        else:
            output.append((content, kind))
    return output
