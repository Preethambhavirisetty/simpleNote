import re
import hashlib
from llama_index.core.node_parser import SemanticSplitterNodeParser
from llama_index.core import Document as LlamaDocument
from llama_index.core import Settings
from core.config import BREAKPOINT_PERCENTILE, MAX_CHUNK_SIZE, CHUNK_OVERLAP

_semantic_splitter = None

HEADING_PATTERN = re.compile(r'\n(?=[A-Z][^.!?\n]{0,60}\n)')
DIVIDER_LINE_PATTERN = re.compile(r'(?m)^[ \t]*[-*_]{3,}[ \t]*$')
SENTINEL_LINE_PATTERN = re.compile(r'(?mi)^[ \t]*\[(?:eof|end)\][ \t]*$')
EMPTY_LIST_ITEM_PATTERN = re.compile(r'(?m)^[ \t]*(?:[*+-]|\d+[.)])[ \t]*$')
NUMBERED_LINE_PATTERN = re.compile(r'^\s*\d+\.\s+(.+)$')



def _split_by_headings(text):
    """Split at lines that look like section headings (short, capitalized, no end punctuation)."""
    parts = HEADING_PATTERN.split(text)
    return [p.strip() for p in parts if p.strip()]


def _inject_numbered_line_breaks(text):
    """
    Force paragraph breaks before any numbered line (e.g., "2. ...")
    so it starts a new chunk even with single newlines.
    """
    lines = text.splitlines()
    output = []
    for line in lines:
        if NUMBERED_LINE_PATTERN.match(line):
            if output and output[-1].strip():
                output.append("")
        output.append(line)
    return "\n".join(output)


def _semantic_split(text):
    """Fall back to semantic splitting for large unstructured text with SemanticSplitterNodeParser"""
    global _semantic_splitter
    if _semantic_splitter is None:
        if not getattr(Settings, "embed_model", None):
            raise RuntimeError(
                "LlamaIndex settings are not initialized. "
                "Call init_llama_index_settings() once at application startup."
            )
        _semantic_splitter = SemanticSplitterNodeParser(
            embed_model=Settings.embed_model,
            breakpoint_percentile_threshold=BREAKPOINT_PERCENTILE,
            buffer_size=1,
        )
    llama_doc = LlamaDocument(text=text)
    nodes = _semantic_splitter.get_nodes_from_documents([llama_doc])
    return [node.get_content() for node in nodes]


def _window_split(text):
    """Hard size cap split with overlap to stabilize retrieval chunk lengths."""
    clean = text.strip()
    if not clean:
        return []
    if len(clean) <= MAX_CHUNK_SIZE:
        return [clean]

    overlap = max(0, min(CHUNK_OVERLAP, max(0, MAX_CHUNK_SIZE - 1)))
    step = max(1, MAX_CHUNK_SIZE - overlap)

    parts = []
    start = 0
    while start < len(clean):
        end = min(start + MAX_CHUNK_SIZE, len(clean))
        if end < len(clean):
            # Prefer cutting at whitespace near the end for better readability.
            cut = clean.rfind(" ", start + int(MAX_CHUNK_SIZE * 0.6), end)
            if cut > start:
                end = cut

        piece = clean[start:end].strip()
        if piece:
            parts.append(piece)

        if end >= len(clean):
            break

        next_start = end - overlap
        if next_start <= start:
            next_start = start + step
        start = next_start

    return parts


def _split_large_text(text):
    """
    Semantic split first, then enforce hard max size with overlap.
    Falls back to window splitting when semantic split fails or returns nothing.
    """
    clean = text.strip()
    if not clean:
        return []
    if len(clean) <= MAX_CHUNK_SIZE:
        return [clean]

    semantic_parts = []
    try:
        semantic_parts = [p.strip() for p in _semantic_split(clean) if p.strip()]
    except Exception:
        semantic_parts = []

    if not semantic_parts:
        semantic_parts = [clean]

    bounded_parts = []
    for part in semantic_parts:
        bounded_parts.extend(_window_split(part))

    return bounded_parts


def validate_chunk(chunk):
    clean = chunk.strip()

    # Empty chunks are not useful.
    if not clean:
        return "DISCARD"

    # 1. TRASH: If it's just a divider/line, kill it.
    if re.match(r'^[ \t]*[-*_]{3,}[ \t]*$', clean):
        return "DISCARD"

    # 2. FRAGMENT: likely incomplete chunk.
    # - Ends with bare list marker (e.g., "3.")
    # - Ends with connector words that usually continue
    if len(clean) < 30 and (
        re.search(r'(?:^|\s)\d+\.$', clean)
        or re.search(r'(?:^|\s)(?:and|or|but|to|of|for|with|in|on|at|by)$', clean, re.IGNORECASE)
    ):
        return "NEEDS_MERGE"

    # 3. Valid chunks should have at least one alpha character.
    if any(char.isalpha() for char in clean):
        return "VALID"

    return "DISCARD"


def _is_heading_like(chunk):
    """Heuristic: short single-line title without sentence-ending punctuation."""
    clean = chunk.strip()
    if not clean or "\n" in clean or len(clean) > 100:
        return False
    if clean.endswith((".", "?", "!", ";")):
        return False
    return any(char.isalpha() for char in clean)


def _is_list_chunk(chunk):
    """True when chunk is primarily bullet or numbered-list lines."""
    lines = [line.strip() for line in chunk.splitlines() if line.strip()]
    if not lines:
        return False
    list_line_pattern = re.compile(r'^(?:[*+-]\s+|\d+[.)]\s+)')
    return all(bool(list_line_pattern.match(line)) for line in lines)


def _has_parent_context(chunk):
    """Parent chunk should look like a heading or heading+body context."""
    first_line = chunk.splitlines()[0].strip() if chunk.strip() else ""
    return (
        _is_heading_like(first_line)
        or first_line.endswith(":")
        or "\n" in chunk
    )


def _is_table_like(chunk):
    """Detect markdown/TSV-like table chunks."""
    lines = [line.strip() for line in chunk.splitlines() if line.strip()]
    if not lines:
        return False

    markdown_table_lines = sum(1 for line in lines if line.count("|") >= 2)
    tsv_like_lines = sum(1 for line in lines if line.count("\t") >= 2)
    has_separator = any(re.match(r'^\|?[-: ]+\|[-|: ]+\|?$', line) for line in lines)
    has_table_header = any(
        ("fuel type" in line.lower() and "volume" in line.lower())
        or ("region" in line.lower() and "tier" in line.lower())
        for line in lines
    )
    return markdown_table_lines >= 2 or tsv_like_lines >= 2 or has_separator or has_table_header


def _is_table_rowish_chunk(chunk):
    """Detect chunks that look like continuation rows of a table."""
    lines = [line.strip() for line in chunk.splitlines() if line.strip()]
    if not lines:
        return False
    row_like = 0
    for line in lines:
        if line.count("|") >= 2 or line.count("\t") >= 2:
            row_like += 1
            continue
        if re.match(r'^[A-Za-z][A-Za-z -]*\t', line):
            row_like += 1
    return row_like >= max(1, len(lines) - 1)


def _is_address_like_chunk(chunk):
    """Detect contact/address blocks that should stay together."""
    lines = [line.strip() for line in chunk.splitlines() if line.strip()]
    if not lines or len(lines) > 6:
        return False
    joined = " ".join(lines).lower()
    keywords = ("office", "hangar", "sector", "colony", "street", "road", "way", "city", "state", "zip")
    has_keyword = any(word in joined for word in keywords)
    likely_heading_only = len(lines) == 1 and _is_heading_like(lines[0])
    return has_keyword and not likely_heading_only


def _merge_table_and_address_chunks(chunks):
    """Merge table continuations and contact/address spillovers with neighbors."""
    merged = []
    for chunk in chunks:
        if merged:
            prev = merged[-1]
            table_merge = (
                (_is_table_like(prev) and _is_table_rowish_chunk(chunk))
                or (_is_table_like(chunk) and _is_table_rowish_chunk(prev))
            )
            address_merge = (
                (_is_address_like_chunk(prev) and not _is_heading_like(chunk))
                or ("contact" in prev.lower() and _is_address_like_chunk(chunk))
            )
            if table_merge or address_merge:
                candidate = f"{prev}\n{chunk}".strip()
                if len(candidate) <= MAX_CHUNK_SIZE:
                    merged[-1] = candidate
                    continue
        merged.append(chunk)
    return merged


def _normalize_chunk_text(chunk):
    """
    Clean common editor-derived artifacts:
    - divider lines
    - sentinel lines like [EOF]
    - empty list markers ("4.", "-", "*")
    - excessive blank lines
    - unbalanced fenced code blocks
    """
    clean = DIVIDER_LINE_PATTERN.sub("", chunk)
    clean = SENTINEL_LINE_PATTERN.sub("", clean)
    clean = EMPTY_LIST_ITEM_PATTERN.sub("", clean)
    clean = re.sub(r"\n{3,}", "\n\n", clean).strip()

    # Keep fenced code blocks syntactically complete for retrieval.
    if clean.count("```") % 2 == 1:
        clean = f"{clean}\n```"

    return clean


def _postprocess_chunks(chunks):
    """
    Final cleanup for retrieval quality:
    - remove divider-only lines
    - merge orphan headings with their following chunk when possible
    - enforce max chunk size after merging
    """
    cleaned_chunks = []
    for chunk in chunks:
        clean = _normalize_chunk_text(chunk)
        if validate_chunk(clean) == "VALID":
            cleaned_chunks.append(clean)

    merged_chunks = []
    i = 0
    while i < len(cleaned_chunks):
        current = cleaned_chunks[i]
        if i + 1 < len(cleaned_chunks):
            nxt = cleaned_chunks[i + 1]
            should_merge_with_next = (
                _is_heading_like(current)
                or current.endswith(":")
                or validate_chunk(current) == "NEEDS_MERGE"
            )
            if should_merge_with_next:
                candidate = f"{current}\n{nxt}".strip()
                if len(candidate) <= MAX_CHUNK_SIZE:
                    merged_chunks.append(candidate)
                    i += 2
                    continue
        merged_chunks.append(current)
        i += 1

    # Parent-child linking: attach list-only chunks to previous header/context chunk.
    linked_chunks = []
    for chunk in merged_chunks:
        if linked_chunks and _is_list_chunk(chunk) and _has_parent_context(linked_chunks[-1]):
            candidate = f"{linked_chunks[-1]}\n{chunk}".strip()
            if len(candidate) <= MAX_CHUNK_SIZE:
                linked_chunks[-1] = candidate
                continue
        linked_chunks.append(chunk)

    final_chunks = []
    for chunk in linked_chunks:
        if len(chunk) <= MAX_CHUNK_SIZE:
            final_chunks.append(chunk)
        else:
            final_chunks.extend(_window_split(chunk))

    final_chunks = _merge_table_and_address_chunks(final_chunks)
    return final_chunks


def _handle_small_paragraph(paragraph, chunks):
    """Handle paragraphs already within MAX_CHUNK_SIZE."""
    verdict = validate_chunk(paragraph)
    if verdict == "VALID":
        chunks.append(paragraph)
        return ""
    if verdict == "NEEDS_MERGE":
        return paragraph
    return ""


def _flush_pending_chunk(pending_chunk, chunks, pending_paragraph):
    """Flush pending heading chunk to output or paragraph carry-over."""
    if not pending_chunk:
        return pending_paragraph

    verdict = validate_chunk(pending_chunk)
    if verdict == "VALID":
        chunks.append(pending_chunk)
    elif verdict == "NEEDS_MERGE":
        pending_paragraph = (
            f"{pending_paragraph}\n{pending_chunk}".strip()
            if pending_paragraph else pending_chunk
        )
    return pending_paragraph


def _process_heading_parts(heading_parts, chunks, pending_paragraph):
    """Process heading-derived parts, preserving current merge semantics."""
    pending_chunk = ""
    for part in heading_parts:
        candidate = f"{pending_chunk}\n{part}".strip() if pending_chunk else part
        if len(candidate) <= MAX_CHUNK_SIZE:
            verdict = validate_chunk(candidate)
            if verdict == "DISCARD":
                pending_chunk = ""
            elif verdict == "VALID":
                chunks.append(candidate)
                pending_chunk = ""
            else:
                pending_chunk = candidate
            continue

        if pending_chunk and validate_chunk(pending_chunk) == "VALID":
            chunks.append(pending_chunk)

        if len(part) <= MAX_CHUNK_SIZE:
            part_verdict = validate_chunk(part)
            if part_verdict == "VALID":
                chunks.append(part)
                pending_chunk = ""
            elif part_verdict == "NEEDS_MERGE":
                pending_chunk = part
            else:
                pending_chunk = ""
        else:
            chunks.extend(_split_large_text(part)) # large text -> semantic split + hard size enforcement
            pending_chunk = ""

    return _flush_pending_chunk(pending_chunk, chunks, pending_paragraph)


def split_into_sections(text):
    """Three-tier splitting: paragraphs -> headings -> semantic."""
    print("Chunking began...")
    text = _inject_numbered_line_breaks(text)
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()] # split into paragraphs
    chunks = []
    pending_paragraph = ""
    for paragraph in paragraphs:
        current_paragraph = f"{pending_paragraph}\n{paragraph}".strip() if pending_paragraph else paragraph
        pending_paragraph = ""

        if len(current_paragraph) <= MAX_CHUNK_SIZE: # if paragraph itself is smaller, add it to chunks
            pending_paragraph = _handle_small_paragraph(current_paragraph, chunks)
            continue

        heading_parts = _split_by_headings(current_paragraph) # split paragraph by headings
        if len(heading_parts) > 1:
            pending_paragraph = _process_heading_parts(heading_parts, chunks, pending_paragraph)
        else: 
            chunks.extend(_split_large_text(current_paragraph)) # no heading split -> semantic split + hard size enforcement

    if pending_paragraph and validate_chunk(pending_paragraph) != "DISCARD":
        chunks.append(pending_paragraph)

    chunks = _postprocess_chunks(chunks)
    print(f"Generated {len(chunks)} chunks.")
    print(f"Original Length: {len(text)} | Chunked Length: {sum(len(c) for c in chunks)}")
    return chunks


def get_document_objects(data):
    if 'text' not in data:
        raise ValueError("provide text to get chunks")
    full_text = data['text']
    chunks = split_into_sections(full_text)
    tenant_id = data.get("tenant_id")
    doc_id = f"{data['userid']}-{data['folder_id']}-{data['note_id']}"
    llama_docs = [
        LlamaDocument(
            id_= hashlib.sha256(f"{data['userid']}-{data['folder_id']}-{data['note_id']}-{chunk}".encode()).hexdigest(),
            text=chunk,
            metadata={
                "doc_id": doc_id,
                "userid": data['userid'],
                "tenant_id": tenant_id,
                "folder_id": data['folder_id'],
                "note_id": data['note_id'],
                "folder_title": data['folder_title'],
                "note_title": data['note_title'],
                "description": data['description'],
                "tags": ','.join(data['tags']),
                "chunkid": idx
            },
            excluded_embed_metadata_keys=['userid', 'folder_id', 'note_id', 'chunkid'],
            excluded_llm_metadata_keys=['userid', 'folder_id', 'note_id', 'chunkid'],
            metadata_template="{key}: {value}",
            text_template="""Context Information:
{metadata_str}

---
Document Content:
{content}
"""
        )
        for idx, chunk in enumerate(chunks, start=1)
    ]

    return doc_id, llama_docs
