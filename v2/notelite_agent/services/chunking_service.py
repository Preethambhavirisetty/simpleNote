import re
import hashlib
import logging
from tokenize import generate_tokens
import httpx
from collections import Counter
from llama_index.core.node_parser import SemanticSplitterNodeParser
from llama_index.core import Document as LlamaDocument
from llama_index.core import Settings
from handlers.keyword_extractor import extract_keywords
from core.config import BREAKPOINT_PERCENTILE, MAX_CHUNK_SIZE, CHUNK_OVERLAP, LLM_API_BASE, LLM_API_KEY

log = logging.getLogger(__name__)

_MISTRAL_TIMEOUT = 120.0  # seconds — allow for cold-start model load

_semantic_splitter = None

HEADING_PATTERN = re.compile(r'\n(?=[A-Z][^.!?\n]{0,60}\n)')
DIVIDER_LINE_PATTERN = re.compile(r'(?m)^[ \t]*[-*_]{3,}[ \t]*$')
SENTINEL_LINE_PATTERN = re.compile(r'(?mi)^[ \t]*\[(?:eof|end)\][ \t]*$')
EMPTY_LIST_ITEM_PATTERN = re.compile(r'(?m)^[ \t]*(?:[*+-]|\d+[.)])[ \t]*$')
NUMBERED_LINE_PATTERN = re.compile(r'^\s*\d+\.\s+(.+)$')
_USELESS_SUMMARY_PATTERNS = re.compile(
    r"""
    no\s+(text|meaningful\s+summary|content|information)\s*(provided|to\s+provide|available|found)|
    nothing\s+to\s+summarize|
    text\s+is\s+(too\s+short|missing)|
    these\s+sentences\s+are\s+for\s+testing|
    no\s+summary\s+to\s+provide|
    \[no\s+text\s+provided|
    cannot\s+summarize|
    please\s+(provide|give)\s+(the\s+)?text|
    i\s+cannot\s+summarize|
    without\s+the\s+text\s+provided|
    provide\s+the\s+text\s+for\s+(me\s+to\s+)?summariz
    """,
    re.IGNORECASE | re.VERBOSE,
)

_MIN_SUMMARY_WORDS = 5   # reject anything shorter than this
_MIN_CHUNK_CHARS_FOR_SUMMARY = 30  # skip Mistral call entirely for very short chunks

_SUMMARIZATION_CHAR_CAP = 2000
_MAX_RECURSION_DEPTH = 5

_TOP_N_KEYWORDS=15


# ------ CHUNK HELPERS ----------------------------------------

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


def _is_useless_summary(text: str) -> bool:
    """Return True when the model produced a refusal/placeholder instead of a real summary."""
    stripped = text.strip()
    if not stripped:
        return True
    if len(stripped.split()) < _MIN_SUMMARY_WORDS:
        return True
    if _USELESS_SUMMARY_PATTERNS.search(stripped):
        return True
    return False


def _summarize_chunk(text: str) -> str:
    """Call Mistral (routed via purpose=summarization) for a concise 1-2 sentence summary.
    Returns an empty string on any failure or when the model produces a placeholder refusal,
    so the caller can fall back gracefully.

    optimization: perform chunking summaries in batches rather than a single text
    """
    stripped = text.strip()
    if not stripped:
        return ""
    if len(stripped) < _MIN_CHUNK_CHARS_FOR_SUMMARY:
        log.debug("Chunk too short for summarization (%d chars): %r", len(stripped), stripped[:40])
        return ""
    try:
        with httpx.Client(timeout=_MISTRAL_TIMEOUT) as client:
            resp = client.post(
                f"{LLM_API_BASE}/chat/completions",
                params={"purpose": "summarization"},
                headers={
                    "Authorization": f"Bearer {LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "mistral-7b",
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are a summarization assistant. "
                                "Write 1-2 sentences that capture the main idea of the text. "
                                "If the text is a heading, label, or single phrase with no body, "
                                "describe what kind of content it introduces. "
                                "Never say 'no text provided' or 'no summary to provide' — "
                                "always produce a real sentence about the content. "
                                "Output only the summary — nothing else."
                            ),
                        },
                        {"role": "user", "content": text},
                    ],
                    "max_tokens": 80,
                    "temperature": 0.1,
                },
            )
        resp.raise_for_status()
        summary = resp.json()["choices"][0]["message"]["content"].strip()
        if _is_useless_summary(summary):
            log.debug("Discarding useless summary (text len=%d): %r", len(text), summary[:80])
            return ""
        return summary
    except Exception as exc:
        log.warning("Mistral summary failed (text len=%d): %s", len(text), exc)
        return ""  # caller falls back to chunk text as summary vector


def _merge_for_summarization(texts: list[str], char_cap: int = _SUMMARIZATION_CHAR_CAP) -> list[str]:
    """Merge adjacent small texts into groups up to char_cap for efficient LLM summarization."""
    groups: list[str] = []
    current_parts: list[str] = []
    current_len = 0
    for text in texts:
        text_len = len(text)
        if current_parts and current_len + text_len > char_cap:
            groups.append("\n\n".join(current_parts))
            current_parts = [text]
            current_len = text_len
        else:
            current_parts.append(text)
            current_len += text_len
    if current_parts:
        groups.append("\n\n".join(current_parts))
    return groups


def _recursive_summarize(chunks: list[str], _depth: int = 0) -> str:
    """Recursively merge and summarize until a single overall summary is produced."""
    if not chunks:
        return ""
    if len(chunks) == 1:
        return _summarize_chunk(chunks[0]) or chunks[0][:200]
    if _depth >= _MAX_RECURSION_DEPTH:
        combined = " ".join(chunks)
        return _summarize_chunk(combined) or combined[:200]

    groups = _merge_for_summarization(chunks)
    summaries = []
    for group in groups:
        summary = _summarize_chunk(group)
        summaries.append(summary if summary else group[:200])

    return _recursive_summarize(summaries, _depth + 1)


def _deduplicate_keywords_llm(keywords: list[str]) -> list[str]:
    """Use LLM to deduplicate keywords into top 15 unique, high-signal themes."""
    if not keywords:
        return []
    keyword_text = ", ".join(keywords)
    try:
        with httpx.Client(timeout=_MISTRAL_TIMEOUT) as client:
            resp = client.post(
                f"{LLM_API_BASE}/chat/completions",
                params={"purpose": "summarization"},
                headers={
                    "Authorization": f"Bearer {LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "mistral-7b",
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are a keyword analysis assistant. "
                                "Given a list of keywords from a document, deduplicate them "
                                "and identify the top 15 unique, high-signal themes. "
                                "Return only the themes, one per line. No numbering, no explanations."
                            ),
                        },
                        {"role": "user", "content": keyword_text},
                    ],
                    "max_tokens": 150,
                    "temperature": 0.1,
                },
            )
        resp.raise_for_status()
        result = resp.json()["choices"][0]["message"]["content"].strip()
        return [line.strip() for line in result.splitlines() if line.strip()][:15]
    except Exception as exc:
        log.warning("LLM keyword dedup failed: %s — using simple dedup", exc)
        seen = set()
        deduped = []
        for kw in keywords:
            lower = kw.lower()
            if lower not in seen:
                seen.add(lower)
                deduped.append(kw)
        return deduped[:15]


def _generate_questions(overall_summary: str) -> list[str]:
    """Generate 5 diverse questions from the overall summary for the questions vector."""
    if not overall_summary:
        return []
    try:
        with httpx.Client(timeout=_MISTRAL_TIMEOUT) as client:
            resp = client.post(
                f"{LLM_API_BASE}/chat/completions",
                params={"purpose": "summarization"},
                headers={
                    "Authorization": f"Bearer {LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "mistral-7b",
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are a question generation assistant. "
                                "Given a summary, generate exactly 5 questions a user might ask:\n"
                                "  1 factual question (specific detail)\n"
                                "  1 conceptual question (what/why/how)\n"
                                "  1 summary question (overall/general)\n"
                                "  1 keyword-style query (short, search-like)\n"
                                "  1 follow-up style question (assumes prior context)\n"
                                "Return only the questions, one per line. No numbering or bullets."
                            ),
                        },
                        {"role": "user", "content": overall_summary},
                    ],
                    "max_tokens": 300,
                    "temperature": 0.3,
                },
            )
        resp.raise_for_status()
        result = resp.json()["choices"][0]["message"]["content"].strip()
        print(f"Generate questions result: {result}")
        return [
            line.strip() for line in result.splitlines()
            if line.strip() and line.strip().endswith("?")
        ][:5]
    except Exception as exc:
        log.warning("Question generation failed: %s", exc)
        return []


def _split_into_sections(text):
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


# ------ PUBLIC API ----------------------------------------

def get_document_objects(data):
    if 'text' not in data:
        raise ValueError("provide text to get chunks")
    full_text = data['text']
    chunks = _split_into_sections(full_text)
    print("***************** Chunking completed! *****************")

    tenant_id = data.get("tenant_id")
    doc_id = f"{data['user_id']}-{data['folder_id']}-{data['note_id']}"

    # ── Step 2: Keyword + entity extraction per chunk ──────────────────────
    chunk_results = [extract_keywords(c, _TOP_N_KEYWORDS) for c in chunks] # [(List[str], List[str]), (List[str], List[str]), ...] 
    chunk_keywords = [kws for kws, _ in chunk_results] # [List[str], List[str], ...]
    chunk_entities = [ents for _, ents in chunk_results] # [List[str], List[str], ...]

    all_keywords = [kw for kws in chunk_keywords for kw in kws] # [str,str...]
    keywords_counter = Counter(all_keywords) # {str:count1, str:count2,...}
    filtered_keywords = [(kw, count) for kw, count in keywords_counter.items() if count >= 2 or len(kw.split()) >= 2] # [(str, count),...]
    sorted_keywords = [kw for (kw, _) in sorted(filtered_keywords, key=lambda x: x[1], reverse=True)[:40]] # [str,str,..]

    all_entities = list(dict.fromkeys(ent for ents in chunk_entities for ent in ents)) # [str, str]

    # ── Step 3: Keyword deduplication via LLM ───────────────────────────
    top_keywords = _deduplicate_keywords_llm(sorted_keywords) if sorted_keywords else [] # 
    print('LLM DEDUP: ', top_keywords)

    print("***************** keywords dedup completed! *****************")

    # ── Steps 4: Recursive summarization ──────────────────────────────
    overall_summary = _recursive_summarize(chunks)

    # ── Step 5: Question generation ─────────────────────────────────────
    global_questions = _generate_questions(overall_summary) if overall_summary else []

    print("***************** recurssive summary + question generations completed! *****************")

    # ── Step 6: Build documents ─────────────────────────────────────────

    def _shared_metadata() -> dict:
        return {
            "doc_id": doc_id,
            "user_id": data['user_id'],
            "tenant_id": tenant_id,
            "folder_id": data['folder_id'],
            "note_id": data['note_id'],
            "folder_title": data['folder_title'],
            "note_title": data['note_title'],
            "description": data['description'],
            "tags": ','.join(data['tags']),
        }

    # -- Summary document (one per note, for doc_summaries collection) --
    summary_doc = None
    if overall_summary:
        # summary_parts = [overall_summary]
        # if top_keywords:
        #     summary_parts.append(f"Keywords: {', '.join(top_keywords)}")
        # if global_questions:
        #     summary_parts.append("Questions:\n" + "\n".join(global_questions))
        # summary_text = "\n\n".join(summary_parts)

        summary_meta = _shared_metadata()
        summary_meta["keywords"] = [
            kw.strip()
            for line in top_keywords
            for kw in line.split(',')
            if kw.strip()
        ]
        summary_meta["entities"] = all_entities
        summary_meta["questions"] = global_questions

        summary_doc = LlamaDocument(
            id_=hashlib.sha256(f"{doc_id}-summary".encode()).hexdigest(),
            text=overall_summary,
            metadata=summary_meta,
        )
        print("***************** summary point created! *****************")

    # -- Chunk documents (one per chunk, for doc_chunks collection) --
    _EXCLUDED_EMBED = ['user_id', 'folder_id', 'note_id', 'chunk_id', 'parent_summary']
    _EXCLUDED_LLM   = ['user_id', 'folder_id', 'note_id', 'chunk_id']

    chunk_docs = []
    for idx, chunk in enumerate(chunks, start=1):
        meta = _shared_metadata()
        meta["chunk_id"] = idx
        meta["keywords"] = [*chunk_keywords[idx - 1]] if idx - 1 < len(chunk_keywords) else []
        meta["entities"] = [*chunk_entities[idx - 1]] if idx - 1 < len(chunk_entities) else []
        meta["parent_summary"] = overall_summary or ""

        chunk_docs.append(
            LlamaDocument(
                id_=hashlib.sha256(f"{doc_id}-{chunk}".encode()).hexdigest(),
                text=chunk,
                metadata=meta,
                excluded_embed_metadata_keys=_EXCLUDED_EMBED,
                excluded_llm_metadata_keys=_EXCLUDED_LLM,
                metadata_template="{key}: {value}",
                text_template=(
                    "Context Information:\n{metadata_str}\n\n"
                    "---\nDocument Content:\n{content}\n"
                ),
            )
        )

    log.info(
        "Built %d chunk docs + summary=%s for doc_id=%s",
        len(chunk_docs), bool(summary_doc), doc_id,
    )
    print("***************** chunks points created! *****************")
    return doc_id, summary_doc, chunk_docs


# if __name__ == '__main__':
#     text = """
# The document/documents begins with the idea that the organization is always doing something, even when it is not doing very much at all. On paper, the system appears organized, but in practice the system is mostly a collection of activities, operations, processes, notes, reports, and discussions that are repeated in different forms throughout the day. During the day, the team talks about coordination, and at night the same team talks about coordination again, but with slightly different words, as if repetition itself were a strategy. The report about the work refers to the report as if the report were both the cause and the effect of the work.

# In the first section, there is a mention of alignment, strategy, management, implementation, workflow, integration, and output. In the second section, those same terms appear again, but they are surrounded by words like thing, stuff, part, item, element, factor, aspect, and piece. The text keeps saying that one thing leads to another thing, that one activity influences another activity, and that one operation affects another operation, yet the exact relationship between these things is never fully explained. The result is a situation where the situation itself becomes the subject of the discussion.

# The project team is described in several ways. Sometimes it is the operations team. Sometimes it is the management team. Sometimes it is the delivery team. Sometimes it is simply the team. Sometimes it is not even a team but a group, a unit, a collection, or a set of people working on the same thing. The document also refers to the organization, the company, the department, the office, and the group as though these were interchangeable, which makes entity extraction difficult. The organization wants better organization, the company wants better coordination, and the department wants better management, but all of these goals are expressed using the same generic language.

# There are multiple references to the phase, the stage, the step, the process, the procedure, the cycle, and the sequence. Every phase contains a review, every review contains a note, every note contains a comment, every comment contains a remark, and every remark contains another reference to the same project. The implementation phase is mentioned alongside the planning phase, the analysis phase, the execution phase, the validation phase, and the closing phase, but each one seems to contain the same content repeated under a different heading. The document makes it look like there are many distinct stages when in reality there is very little variation.

# The text also includes a long discussion of data, logs, records, outputs, results, metrics, values, and summaries. The data is said to support the report, but the report is also said to define the data. The logs are said to show the output, but the output is also said to confirm the logs. The metrics are said to measure performance, but performance is never clearly separated from activity, work, or output. This creates a loop in which every noun points back to another noun, and every conclusion points back to the original statement.

# Sometimes the document switches to more abstract language. It talks about improvement, optimization, efficiency, quality, consistency, reliability, structure, clarity, and stability. These are repeated in different combinations, often with modifiers like better, more, less, stronger, clearer, faster, and simpler. The text claims that the workflow should be clearer, the operations should be smoother, the coordination should be stronger, the management should be better, and the integration should be tighter, but these claims are not backed by concrete detail. Instead, the document uses phrases like “the thing we need,” “the way forward,” “the right approach,” and “the better path,” which sound useful but do not add much semantic precision.

# At several points, the document becomes circular. It says that the report should improve the report. It says that the summary should summarize the summary. It says that the review should review the review. It says that the process should process the process. It says that the system should stabilize the system. These statements are grammatically valid but semantically weak. They create a worst-case scenario for a keyword extractor because the same words appear in many contexts, often without clear importance or hierarchy.

# The final section repeats the core themes one more time: team, report, work, process, system, output, management, operations, coordination, integration, workflow, phase, data, log, result, organization, and situation. The conclusion does not introduce new information; it only rephrases what has already been said. If a keyword extractor relies too heavily on frequency, it may surface the wrong terms. If it relies too heavily on shallow phrase matching, it may keep phrases that are merely repeated rather than truly meaningful. If it relies too heavily on surface form without normalization, it may treat plural and singular variants as unrelated terms even though they refer to the same concept.

# In that sense, the document is designed to be difficult. It is long enough to create many candidate spans, repetitive enough to inflate common terms, abstract enough to blur semantic boundaries, and vague enough to make subphrase pruning uncertain. It includes multiple references to day and night, to the same idea expressed in different ways, to overlapping concepts like management and coordination, and to generic nouns like thing, stuff, part, piece, item, and element. A keyword extractor has to decide what matters most, even though the text keeps suggesting that almost everything matters equally. That is exactly what makes it a useful stress test.
# """
#     import time
#     start = time.time()
#     data = {
#         "text": text,
#         "user_id": "SAMPLEUSER01",
#         "folder_id": "SAMPLESFOLDER01",
#         "note_id": "SAMPLENOTE01",
#         "role": "user",
#         "tenant_id": "TENANT01",
#         "folder_title": "SAMPLE FOLDER TITLE1",
#         "note_title": "SAMPLE NOTE TITLE1",
#         "description": "SAMPLE DESCRIPTION 1",
#         "tags": [
#             "tag1",
#             "tag2"
#         ]
#     }
#     _run_ingestion(data)
#     print("Total ingestion time: ", time.time() - start)





''' SAVING THIS FOR THE PLAN IN DOC STRING
def get_document_objects(data):
    """ Hierarchical RAG System (Production-Ready Design)
    This system uses two vector collections:
    1. doc_summaries:
    - doc_id
    - text = (overall_summary + top_keywords + generated_questions)
    - metadata

    2. doc_chunks:
    - doc_id
    - text = (raw_chunk_text)
    - metadata:
            - keywords
            - parent_summary  # critical for local + global context
            - additional metadata fields

    --------------------------------------------------
    1. INGESTION PIPELINE (Bottom-Up, Recursive Summarization)

    Step 1: Chunk Processing: which we already have

    Step 2: Keyword Extraction
    - For each chunk:
        - Extract keywords using hybrid approach:
            - YAKE (statistical)
            - spaCy (linguistic)
        - Store keywords in chunk metadata.

    Step 3: Controlled Chunk Merging for Summarization
    - Combine adjacent chunks until reaching a token cap (e.g., 50 tokens).
    - Example:
        - chunk1 (10 tokens) + chunk2 (30 tokens) → merged
        - chunk3 (100 tokens) → standalone
    - For each merged group:
        - Call LLM to generate a summary.
    - Collect all intermediate summaries.

    Step 4: Recursive Summarization
    - Repeat the merging + summarization process hierarchically:
        - Summaries → higher-level summaries
    - Continue until a single "overall_summary" is produced.

    Step 5: Keyword Deduplication (Critical)
    - Aggregate all extracted keywords across chunks.
    - Send to LLM with instruction:
        "Deduplicate into top 15 unique, high-signal themes."
    - Result: clean, non-redundant keyword set.

    Step 6: Question Generation
    - Use final overall_summary to generate 2–3 global questions.
    - These help retrieval via semantic matching.

    Step 7: Storage
    - doc_summaries:
        - Store:
            overall_summary + top_15_keywords + global_questions

    - doc_chunks:
        - Store:
            raw chunk text
            keywords
            parent_summary (overall_summary or nearest higher-level summary)

    --------------------------------------------------
    2. RETRIEVAL PIPELINE (Smart Router + Fusion)

    Step 1: Query doc_summaries
    - Perform semantic search on summaries.
    - Retrieve top results with similarity scores.

    Step 2: Filtering Logic
    - Select documents where score > 0.8 → filtered_docs

    - If many matches:
        - Limit to Top 3 doc_ids (prevents noisy search space)

    Step 3: Score Gap Check (Uniform Document Edge Case)
    - If (S1 - S2) < 0.05:
        - Summaries are too similar → system is "confused"
        - Trigger fallback immediately

    Step 4: Fallback Condition
    - If all summary scores < 0.7:
        - Skip summary filtering
        - Perform global search directly on doc_chunks

    Step 5: Chunk Retrieval
    - If filtered_docs available:
        - Query doc_chunks restricted to top doc_ids
    - Else:
        - Query all doc_chunks

    - Perform two parallel retrieval strategies:
        1. Semantic search (vector similarity)
        2. Keyword/metadata match (lexical)

    Step 6: Fusion (RRF - Reciprocal Rank Fusion)
    - Combine semantic + lexical results using RRF
    - Produces robust, hybrid ranking

    --------------------------------------------------
    3. EDGE CASE HANDLING

    1. Uniform Documents:
        - Problem: All summaries have similar scores (e.g., legal docs)
        - Solution:
            - Use score gap rule: (S1 - S2) < 0.05 → fallback to chunk search

    2. Cross-Document Queries:
        - Problem: Answer spans multiple documents
        - Solution:
            - Always allow top 2–3 doc_ids into chunk retrieval

    3. Keyword Overlap:
        - Problem: Query keyword exists in chunks but not summaries
        - Solution:
            - If summary scores < 0.7 → global chunk fallback

    4. Summary Hallucination / Missing Detail:
        - Problem: Summary omits critical info
        - Solution:
            - ALWAYS include raw chunk text in final LLM context
            - Never rely solely on summaries

    --------------------------------------------------
    4. FINAL LLM PROMPT CONSTRUCTION

    - For each retrieved chunk:
        - Include:
            - chunk.text (ground truth)
            - parent_summary (contextual overview)

    - Combine:
        - Top-ranked chunks (via RRF)
        - Relevant summaries (if useful)

    - Send to LLM for final answer generation.

    --------------------------------------------------
    Key Design Principles:
    - Preserve small but important data (no chunk loss)
    - Control noise via top-k filtering
    - Use hybrid retrieval (semantic + lexical)
    - Always maintain fallback paths
    - Provide both local (chunk) and global (summary) context
    """

    if 'text' not in data:
        raise ValueError("provide text to get chunks")
    full_text = data['text']
    chunks = split_into_sections(full_text)

    tenant_id = data.get("tenant_id")
    doc_id = f"{data['user_id']}-{data['folder_id']}-{data['note_id']}"

    # ── Step 2: Keyword + entity extraction per chunk ──────────────────
    chunk_results = [extract_keywords(c) for c in chunks]
    chunk_keywords = [kws for kws, _ in chunk_results]
    chunk_entities = [ents for _, ents in chunk_results]

    all_keywords = [kw for kws in chunk_keywords for kw in kws]
    all_entities = list(dict.fromkeys(ent for ents in chunk_entities for ent in ents))

    # ── Steps 3-4: Recursive summarization ──────────────────────────────
    overall_summary = _recursive_summarize(chunks)

    # ── Step 5: Keyword deduplication via LLM ───────────────────────────
    top_keywords = _deduplicate_keywords_llm(all_keywords) if all_keywords else []

    # ── Step 6: Question generation ─────────────────────────────────────
    global_questions = _generate_questions(overall_summary) if overall_summary else []

    # ── Step 7: Build documents ─────────────────────────────────────────

    def _shared_metadata() -> dict:
        return {
            "doc_id": doc_id,
            "user_id": data['user_id'],
            "tenant_id": tenant_id,
            "folder_id": data['folder_id'],
            "note_id": data['note_id'],
            "folder_title": data['folder_title'],
            "note_title": data['note_title'],
            "description": data['description'],
            "tags": ','.join(data['tags']),
        }

    # -- Summary document (one per note, for doc_summaries collection) --
    summary_doc = None
    if overall_summary:
        summary_parts = [overall_summary]
        if top_keywords:
            summary_parts.append(f"Keywords: {', '.join(top_keywords)}")
        if global_questions:
            summary_parts.append("Questions:\n" + "\n".join(global_questions))
        summary_text = "\n\n".join(summary_parts)

        summary_meta = _shared_metadata()
        summary_meta["keywords"] = ','.join(top_keywords)
        summary_meta["entities"] = ','.join(all_entities)

        summary_doc = LlamaDocument(
            id_=hashlib.sha256(f"{doc_id}-summary".encode()).hexdigest(),
            text=summary_text,
            metadata=summary_meta,
        )

    # -- Chunk documents (one per chunk, for doc_chunks collection) --
    _EXCLUDED_EMBED = ['user_id', 'folder_id', 'note_id', 'chunk_id', 'parent_summary']
    _EXCLUDED_LLM   = ['user_id', 'folder_id', 'note_id', 'chunk_id']

    chunk_docs = []
    for idx, chunk in enumerate(chunks, start=1):
        meta = _shared_metadata()
        meta["chunk_id"] = idx
        meta["keywords"] = ','.join(
            chunk_keywords[idx - 1] if idx - 1 < len(chunk_keywords) else []
        )
        meta["entities"] = ','.join(
            chunk_entities[idx - 1] if idx - 1 < len(chunk_entities) else []
        )
        meta["parent_summary"] = overall_summary or ""

        chunk_docs.append(
            LlamaDocument(
                id_=hashlib.sha256(f"{doc_id}-{chunk}".encode()).hexdigest(),
                text=chunk,
                metadata=meta,
                excluded_embed_metadata_keys=_EXCLUDED_EMBED,
                excluded_llm_metadata_keys=_EXCLUDED_LLM,
                metadata_template="{key}: {value}",
                text_template=(
                    "Context Information:\n{metadata_str}\n\n"
                    "---\nDocument Content:\n{content}\n"
                ),
            )
        )

    log.info(
        "Built %d chunk docs + summary=%s for doc_id=%s",
        len(chunk_docs), bool(summary_doc), doc_id,
    )
    return doc_id, summary_doc, chunk_docs


'''