import re


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
    return any(char.isalpha() for char in clean)


def is_list_chunk(chunk: str) -> bool:
    lines = [line.strip() for line in chunk.splitlines() if line.strip()]
    if not lines:
        return False

    list_line_pattern = re.compile(r"^(?:[*+-]\s+|\d+[.)]\s+)")
    return all(bool(list_line_pattern.match(line)) for line in lines)


def has_parent_context(chunk: str) -> bool:
    first_line = chunk.splitlines()[0].strip() if chunk.strip() else ""
    return is_heading_like(first_line) or first_line.endswith(":") or "\n" in chunk


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


def is_address_like_chunk(chunk: str) -> bool:
    lines = [line.strip() for line in chunk.splitlines() if line.strip()]
    if not lines or len(lines) > 6:
        return False

    joined = " ".join(lines).lower()
    keywords = (
        "office",
        "hangar",
        "sector",
        "colony",
        "street",
        "road",
        "way",
        "city",
        "state",
        "zip",
    )
    has_keyword = any(word in joined for word in keywords)
    likely_heading_only = len(lines) == 1 and is_heading_like(lines[0])

    return has_keyword and not likely_heading_only
