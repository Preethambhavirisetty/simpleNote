import re

from app.services.ingestion.processors.chunking.chunk_types import classify_chunk_type
from app.services.ingestion.processors.chunking.patterns import DIVIDER_LINE_PATTERN


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


def split_into_typed_chunks(text: str) -> list[tuple[str, str]]:
    """Split a document on structural boundaries, then classify each block."""
    clean = text.strip()
    if not clean:
        return []

    nonempty_lines = [line.strip() for line in clean.splitlines() if line.strip()]
    if nonempty_lines and all(DIVIDER_LINE_PATTERN.fullmatch(line) for line in nonempty_lines):
        return []

    whole_type = classify_chunk(clean)
    has_markdown_headings = bool(re.search(r"^#{1,6}\s+\S", clean, re.MULTILINE))
    atomic_types = {
        "address", "contact", "faq", "glossary", "json", "list", "quote",
        "structured_list",
    }
    if whole_type in atomic_types and not has_markdown_headings:
        return [(clean, whole_type)]
    if whole_type == "content" and not re.search(r"^#{1,6}\s+\S", clean, re.MULTILINE):
        paragraph_types = [classify_chunk(block) for kind, block in _structural_blocks(clean) if kind == "prose"]
        has_structural_blocks = any(kind in {"code", "divider", "json", "table"} for kind, _ in _structural_blocks(clean))
        if not has_structural_blocks and "code" not in paragraph_types:
            return [(clean, whole_type)]
    if whole_type in {"heading_only", "transcript"} and not has_markdown_headings and "```" not in clean and "~~~" not in clean:
        return [(clean, whole_type)]
    if whole_type in {"code", "table"} and "\n\n" not in clean:
        return [(clean, whole_type)]

    blocks = _structural_blocks(clean)
    chunks: list[tuple[str, str]] = []
    headings: list[str] = []
    force_boundary = False

    def emit(content: str, chunk_type: str | None = None) -> None:
        nonlocal force_boundary
        value = content.strip()
        if not value:
            return
        kind = chunk_type or classify_chunk(value)
        if not force_boundary and chunks and kind == "content" and chunks[-1][1] == "content" and not _starts_markdown_heading(value):
            previous, _ = chunks[-1]
            chunks[-1] = (f"{previous}\n\n{value}", kind)
        else:
            chunks.append((value, kind))
        force_boundary = False

    for block_kind, block in blocks:
        if block_kind == "divider":
            force_boundary = True
            continue

        if block_kind == "heading":
            depth = _heading_depth(block)
            if headings and depth <= _heading_depth(headings[-1]):
                emit("\n\n".join(headings), "heading_only")
                headings = headings[: max(0, depth - 1)]
            headings.append(block)
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

        emit(block, kind)

    if headings:
        emit("\n\n".join(headings), "heading_only")


    chunks = _merge_dialogue_chunks(chunks, whole_type == "transcript")
    has_subsections = any(re.match(r"^#{2,6}\s+\S", line.strip()) for content, _ in chunks for line in content.splitlines())
    if not has_subsections:
        chunks = _merge_same_type_lists(chunks)
    if not has_subsections and not any(kind in {"code", "json", "table"} for _, kind in chunks) and any(kind in {"list", "structured_list", "transcript"} for _, kind in chunks):
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

        if DIVIDER_LINE_PATTERN.fullmatch(stripped):
            flush_paragraph()
            flush_table()
            blocks.append(("divider", ""))
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
    list_indexes = [
        index for index, (content, kind) in enumerate(chunks)
        if kind in {"list", "structured_list"} and not _starts_markdown_heading(content)
    ]
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
            previous, _ = output[-1]
            headings = dict.fromkeys(
                line.strip()
                for value in (previous, content)
                for line in value.splitlines()
                if line.strip()
            )
            output[-1] = ("\n\n".join(headings), kind)
        else:
            output.append((content, kind))
    return output
