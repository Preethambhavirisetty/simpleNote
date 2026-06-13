from __future__ import annotations

import re


MARKDOWN_TABLE_SEPARATOR_PATTERN = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)+\|?\s*$")


def repair_ocr_hyphenation(text: str) -> str:
    """Join words split by OCR or PDF line wrapping, e.g. experi-\nence."""
    return re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)


def normalize_markdown_tables_for_terms(text: str) -> str:
    lines = text.splitlines()
    output: list[str] = []
    table_lines: list[str] = []

    def flush_table() -> None:
        if not table_lines:
            return
        output.extend(_table_lines_to_text(table_lines))
        table_lines.clear()

    for line in lines:
        if _is_markdown_table_line(line):
            table_lines.append(line)
            continue
        flush_table()
        output.append(line)

    flush_table()
    return "\n".join(output)


def augment_markdown_table(content: str, heading_context: str = "") -> str:
    """Describe a Markdown table as natural language for search and term extraction."""
    lines = [line.strip() for line in content.splitlines() if "|" in line]
    rows = [
        _split_table_cells(line)
        for line in lines
        if not MARKDOWN_TABLE_SEPARATOR_PATTERN.match(line.strip())
    ]
    if len(rows) < 2 or not rows[0]:
        return ""

    header = rows[0]
    data_rows = [row for row in rows[1:] if len(row) == len(header)]
    if not data_rows:
        return ""

    parts = []
    if heading_context:
        parts.append(f"Table from section: {heading_context}.")
    parts.append(f"Columns: {', '.join(header)}.")
    row_label = "row" if len(data_rows) == 1 else "rows"
    parts.append(f"Contains {len(data_rows)} {row_label}.")
    for row in data_rows:
        parts.append(", ".join(f"{key} {value}" for key, value in zip(header, row)) + ".")
    return " ".join(parts)


def normalize_text_for_keyword_extraction(text: str) -> str:
    clean = repair_ocr_hyphenation(text)
    clean = normalize_markdown_tables_for_terms(clean)
    clean = _separate_structural_headings(clean)
    return clean


def markdown_table_headers(text: str) -> list[str]:
    """Return the first valid Markdown table row as its column headers."""
    lines = [line for line in text.splitlines() if _is_markdown_table_line(line)]
    rows = [
        _split_table_cells(line)
        for line in lines
        if not MARKDOWN_TABLE_SEPARATOR_PATTERN.match(line.strip())
    ]
    return rows[0] if len(rows) >= 2 else []


def without_markdown_heading_lines(text: str) -> str:
    """Remove structural Markdown heading lines while preserving body text."""
    return "\n".join(
        line for line in text.splitlines()
        if not _is_markdown_heading(line.strip())
    ).strip()


def _is_markdown_table_line(line: str) -> bool:
    clean = line.strip()
    return clean.count("|") >= 2 or bool(MARKDOWN_TABLE_SEPARATOR_PATTERN.match(clean))


def _split_table_cells(line: str) -> list[str]:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return [cell for cell in cells if cell]


def _table_lines_to_text(lines: list[str]) -> list[str]:
    rows = [
        _split_table_cells(line)
        for line in lines
        if not MARKDOWN_TABLE_SEPARATOR_PATTERN.match(line.strip())
    ]
    if not rows:
        return []

    header = rows[0]
    body_rows = rows[1:] if len(rows) > 1 else rows
    output = []
    for row in body_rows:
        if not row:
            continue
        paired = [
            f"{header[index]} {cell}"
            for index, cell in enumerate(row)
            if index < len(header) and header[index] and cell
        ]
        output.append(" ".join(paired) if paired else " ".join(row))
    return output


def _separate_structural_headings(text: str) -> str:
    lines = []
    for line in text.splitlines():
        clean = line.strip()
        if _is_markdown_heading(clean) or _is_short_label_heading(clean):
            clean = clean.rstrip(":")
            if clean and clean[-1] not in ".?!":
                line = f"{clean}."
        lines.append(line)
    return "\n".join(lines)


def _is_markdown_heading(line: str) -> bool:
    return bool(re.match(r"^#{1,6}\s+\S", line))


def _is_short_label_heading(line: str) -> bool:
    if "\t" in line or "|" in line or not line:
        return False
    clean = re.sub(r"^\d+(?:\.\d+)*(?:\.)?\s+", "", line).strip()
    if len(clean) > 80 or len(clean.split()) > 8:
        return False
    return bool(re.match(r"^[A-Z][^.!?]*:?$", clean))
