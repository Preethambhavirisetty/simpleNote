import re

TOP_LEVEL_HEADING_PATTERN = re.compile(r"^\s*(?P<number>\d+)(?:\.\d+)*(?:\.)?\s+")
NUMBERED_HEADING_PREFIX_PATTERN = re.compile(r"^\s*(?P<prefix>\d+(?:\.\d+)*)(?:\.)?\s+")
NUMBERED_LIST_ITEM_PATTERN = re.compile(r"^\s*\d+[.)]\s+")
FENCED_CODE_BLOCK_PATTERN = re.compile(r"```[^\n]*\n[\s\S]*?\n```", re.DOTALL)
FENCED_CODE_BLOCK_LINE_PATTERN = re.compile(r"^```.*", re.MULTILINE)
BOUNDARY_HEADING_PATTERN = re.compile(
    r"^(?:#{1,6}\s*)?(?:appendix|glossary|faq|faqs|transcript|table|references?|bibliography|index)\b",
    re.IGNORECASE,
)
EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
PHONE_PATTERN = re.compile(r"(?:\+?\d[\d().\-\s]{6,}\d)")
URL_PATTERN = re.compile(r"\b(?:https?://|www\.)\S+\b", re.IGNORECASE)
STREET_ADDRESS_PATTERN = re.compile(
    r"\b\d{1,6}\s+[A-Za-z0-9][A-Za-z0-9 .'-]*\b(?:"
    r"street|st\.?|road|rd\.?|avenue|ave\.?|boulevard|blvd\.?|drive|dr\.?|"
    r"lane|ln\.?|court|ct\.?|circle|cir\.?|place|pl\.?|parkway|pkwy\.?|way|terrace|ter\.?"
    r")\b",
    re.IGNORECASE,
)
POSTAL_CODE_PATTERN = re.compile(
    r"\b(?:[A-Z]{2}\s+\d{5}(?:-\d{4})?|\d{5}(?:-\d{4})?|[A-Z]\d[A-Z]\s?\d[A-Z]\d)\b"
)


def validate_chunk(chunk: str) -> str:
    clean = chunk.strip()

    if not clean:
        return "DISCARD"

    if re.match(r"^[ \t]*[-*_]{3,}[ \t]*$", clean):
        return "DISCARD"

    if len(clean) < 30 and (
        re.search(r"(?:^|\s)\d+\.$", clean)
        or re.search(
            r"(?:^|\s)(?:and|or|but|to|of|for|with|in|on|at|by)$",
            clean,
            re.IGNORECASE,
        )
    ):
        return "NEEDS_MERGE"

    if any(char.isalpha() for char in clean):
        return "VALID"

    return "DISCARD"


def is_heading_like(chunk: str) -> bool:
    clean = chunk.strip()
    if not clean or "\n" in clean or len(clean) > 100:
        return False
    if clean.endswith((".", "?", "!", ";")):
        return False
    if re.match(r"^(?:\d+(?:\.\d+)*(?:\.)?)\s+", clean):
        return True
    return any(char.isalpha() for char in clean)


def is_list_chunk(chunk: str) -> bool:
    lines = [line.strip() for line in chunk.splitlines() if line.strip()]
    if not lines:
        return False

    list_line_pattern = re.compile(r"^(?:[*+-]\s+|\d+[.)]\s+)")
    if len(lines) == 1:
        # Treat a lone bullet item as a list, but avoid single numbered headings.
        return bool(re.match(r"^(?:[*+-]\s+|\d+\)\s+)", lines[0]))

    return all(bool(list_line_pattern.match(line)) for line in lines)


def is_numbered_list_part(chunk: str) -> bool:
    lines = [line.strip() for line in chunk.splitlines() if line.strip()]
    if not lines:
        return False
    return all(bool(NUMBERED_LIST_ITEM_PATTERN.match(line)) for line in lines)


def is_numbered_list_item(chunk: str) -> bool:
    first_line = chunk.splitlines()[0].strip() if chunk.strip() else ""
    return bool(NUMBERED_LIST_ITEM_PATTERN.match(first_line))


def is_fenced_code_block(chunk: str) -> bool:
    content = chunk.strip()
    return bool(FENCED_CODE_BLOCK_PATTERN.fullmatch(content))


def split_preserving_fenced_code_blocks(text: str) -> list[str]:
    segments: list[str] = []
    last = 0
    for match in FENCED_CODE_BLOCK_PATTERN.finditer(text):
        if match.start() > last:
            segments.append(text[last:match.start()])
        segments.append(match.group(0))
        last = match.end()

    if last < len(text):
        segments.append(text[last:])
    return segments


def is_inside_fenced_code(text: str, index: int) -> bool:
    fences = list(FENCED_CODE_BLOCK_LINE_PATTERN.finditer(text[:index]))
    return len(fences) % 2 == 1


def heading_number_prefix(chunk: str) -> str | None:
    prefixes = []
    for line in chunk.splitlines():
        clean = line.strip()
        if not clean:
            continue
        prefixes.extend(
            re.findall(r"(?:^|>\s*)(\d+(?:\.\d+)*)(?:\.)?\s+", clean)
        )

    if prefixes:
        return prefixes[-1]

    first_line = chunk.splitlines()[0].strip() if chunk.strip() else ""
    match = NUMBERED_HEADING_PREFIX_PATTERN.match(first_line)
    return match.group("prefix") if match else None


def has_parent_context(chunk: str) -> bool:
    first_line = chunk.splitlines()[0].strip() if chunk.strip() else ""
    return is_heading_like(first_line) or first_line.endswith(":") or "\n" in chunk


def is_boundary_heading(chunk: str) -> bool:
    first_line = chunk.splitlines()[0].strip() if chunk.strip() else ""
    first_line = re.sub(r"^\d+(?:\.\d+)*(?:\.)?\s+", "", first_line).strip()
    return bool(BOUNDARY_HEADING_PATTERN.match(first_line))


def top_level_heading(chunk: str) -> str | None:
    first_line = chunk.splitlines()[0].strip() if chunk.strip() else ""
    match = TOP_LEVEL_HEADING_PATTERN.match(first_line)
    return match.group("number") if match else None


def is_table_like(chunk: str) -> bool:
    lines = [line.strip() for line in chunk.splitlines() if line.strip()]
    if not lines:
        return False

    markdown_table_lines = sum(1 for line in lines if line.count("|") >= 2)
    tsv_like_lines = sum(1 for line in lines if line.count("\t") >= 2)
    has_separator = any(re.match(r"^\|?[-: ]+\|[-|: ]+\|?$", line) for line in lines)
    has_table_header = any(
        ("fuel type" in line.lower() and "volume" in line.lower())
        or ("region" in line.lower() and "tier" in line.lower())
        for line in lines
    )

    return markdown_table_lines >= 2 or tsv_like_lines >= 2 or has_separator or has_table_header


def is_table_rowish_chunk(chunk: str) -> bool:
    lines = [line.strip() for line in chunk.splitlines() if line.strip()]
    if not lines:
        return False

    row_like = 0
    for line in lines:
        if line.count("|") >= 2 or line.count("\t") >= 2:
            row_like += 1
            continue
        if re.match(r"^[A-Za-z][A-Za-z -]*\t", line):
            row_like += 1

    return row_like >= max(1, len(lines) - 1)


def is_heading_only_chunk(chunk: str) -> bool:
    lines = [line.strip() for line in chunk.splitlines() if line.strip()]
    if not lines:
        return False
    return all(_is_structural_heading_line(line) for line in lines)


def _is_structural_heading_line(line: str) -> bool:
    clean = line.strip()
    if not clean or len(clean) > 140:
        return False
    if re.match(r"^#{1,6}\s+\S", clean):
        return True
    if clean.endswith(":") and len(clean.split()) <= 8:
        return True
    return False


def is_signature_like_chunk(chunk: str) -> bool:
    lines = [line.strip() for line in chunk.splitlines() if line.strip()]
    if not lines or len(lines) > 8:
        return False

    joined = " ".join(lines).lower()
    contact_markers = ("best regards", "sincerely")
    if EMAIL_PATTERN.search(joined) or URL_PATTERN.search(joined):
        return True
    return any(marker in joined for marker in contact_markers)


def is_contact_like_chunk(chunk: str) -> bool:
    text = chunk.strip()
    if not text:
        return False

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    joined = " ".join(lines)
    lowered = joined.lower()

    has_direct_contact = (
        EMAIL_PATTERN.search(joined) is not None
        or URL_PATTERN.search(joined) is not None
        or PHONE_PATTERN.search(joined) is not None
    )
    has_address = (
        STREET_ADDRESS_PATTERN.search(joined) is not None
        or POSTAL_CODE_PATTERN.search(joined) is not None
    )
    has_contact_heading = bool(
        re.search(r"^#{1,6}\s+(?:contact|contact information)\b", text, re.IGNORECASE)
    )
    has_explicit_label = bool(
        re.search(r"\b(?:email|phone|fax|website|address|inquiries)\s*:", lowered)
    )

    return has_direct_contact or has_contact_heading or has_explicit_label or has_address

def is_address_like_chunk(chunk: str) -> bool:
    lines = [line.strip() for line in chunk.splitlines() if line.strip()]
    if not lines or len(lines) > 6:
        return False

    joined = " ".join(lines).lower()
    keywords = (
        "office",
        "headquarters",
        "hangar",
        "sector",
        "colony",
        "street",
        "road",
        "drive",
        "suite",
        "place",
        "strasse",
        "straße",
        "gmbh",
        "pte.",
        "inc.",
        "city",
        "zip",
        "phone",
        "fax",
        "inquiries",
        "support",
        "security",
        "protection",
    )
    has_keyword = any(re.search(rf"\b{re.escape(word)}\b", joined) for word in keywords)
    has_postal_line = any(
        re.search(r"\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b", line)
        or re.search(r"\b\d{5}\s+[A-Za-z]", line)
        or re.search(r"\bSingapore\s+\d{6}\b", line, re.IGNORECASE)
        for line in lines
    )
    has_street_line = any(STREET_ADDRESS_PATTERN.search(line) for line in lines)
    likely_heading_only = len(lines) == 1 and is_heading_like(lines[0])

    return (has_postal_line or has_street_line) and not likely_heading_only
