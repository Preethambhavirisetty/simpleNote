import re
import hashlib
import logging
import httpx
from llama_index.core.node_parser import SemanticSplitterNodeParser
from llama_index.core import Document as LlamaDocument
from llama_index.core import Settings
from core.config import BREAKPOINT_PERCENTILE, MAX_CHUNK_SIZE, CHUNK_OVERLAP, LLM_API_BASE, LLM_API_KEY

log = logging.getLogger(__name__)

_MISTRAL_TIMEOUT = 120.0  # seconds — allow for cold-start model load

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


def _get_keywords(chunk):
    result = []
    words = re.findall(r'\w+', chunk.strip())  # findall returns a list; re.search returns a Match
    for word in words:
        if len(word) >= 6:
            result.append(word)
    return result


def extract_keywords(text=""):
    # keywords = []
    # for chunk in chunks:
    #     keywords.extend(_get_keywords(chunk))
    # return ', '.join(keywords)
    import yake

    kw_extractor = yake.KeywordExtractor(lan="en", n=2, top=5)
    keywords = kw_extractor.extract_keywords(text)

    # Returns a list of (keyword, score) - lower score is more relevant in YAKE
    for kw, score in keywords:
        print(f"{kw}: {score}")

def extract_keywords2(text):
    import spacy

    nlp = spacy.load("en_core_web_sm")
    doc = nlp(text)

    # Extract Proper Nouns (PROPN) or specific Entities (ORG, PERSON, GPE)
    entities = [ent.text for ent in doc.ents if ent.label_ in ["ORG", "PRODUCT"]]

    print(entities)


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
    """Call Mistral (routed via purpose=query_parsing) for a concise 1-2 sentence summary.
    Returns an empty string on any failure or when the model produces a placeholder refusal,
    so the caller can fall back gracefully.
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
                params={"purpose": "query_parsing"},
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


def handle_chunk_summaries(chunks: list) -> tuple:
    """Summarize every chunk with Mistral, then produce one overall document summary.

    Returns:
        chunk_summaries   one string per chunk (same order); empty string if Mistral failed.
        overall_summary   single summary combining all chunk summaries; empty string on failure.

    The caller must not fail if summaries are empty — the named-vector upsert falls back to
    embedding the raw chunk text for the summary vector in that case.
    """
    chunk_summaries = [_summarize_chunk(c) for c in chunks]
    combined = " ".join(s for s in chunk_summaries if s)
    overall_summary = _summarize_chunk(combined) if combined else ""
    return chunk_summaries, overall_summary


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
    # Per-chunk summaries + one overall summary (both generated by Mistral).
    # Both return empty strings when Mistral is unavailable — handled gracefully below.
    chunk_summaries, overall_summary = handle_chunk_summaries(chunks)
    tenant_id = data.get("tenant_id")
    doc_id = f"{data['user_id']}-{data['folder_id']}-{data['note_id']}"

    def _base_metadata(chunk_id: int, summary: str) -> dict:
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
            "chunk_id": chunk_id,
            # Stored for the summary_vec embedding path in the Qdrant handler.
            # Excluded from LlamaIndex's rendered text template to avoid double-counting.
            "summary": summary,
        }

    _EXCLUDED_EMBED = ['user_id', 'folder_id', 'note_id', 'chunk_id', 'summary']
    _EXCLUDED_LLM   = ['user_id', 'folder_id', 'note_id', 'chunk_id', 'summary']

    llama_docs = [
        LlamaDocument(
            id_=hashlib.sha256(
                f"{data['user_id']}-{data['folder_id']}-{data['note_id']}-{chunk}".encode()
            ).hexdigest(),
            text=chunk,
            metadata=_base_metadata(
                chunk_id=idx,
                summary=chunk_summaries[idx - 1] if chunk_summaries and idx - 1 < len(chunk_summaries) else "",
            ),
            excluded_embed_metadata_keys=_EXCLUDED_EMBED,
            excluded_llm_metadata_keys=_EXCLUDED_LLM,
            metadata_template="{key}: {value}",
            text_template="Context Information:\n{metadata_str}\n\n---\nDocument Content:\n{content}\n",
        )
        for idx, chunk in enumerate(chunks, start=1)
    ]

    # Overall-summary document (chunk_id=0): a single point whose text IS the Mistral
    # summary of the entire note.  It is embedded in both vector spaces so broad queries
    # like "what is this note about?" surface it before individual chunks.
    # Skipped when Mistral was unavailable (overall_summary is empty).
    if overall_summary:
        overview_doc = LlamaDocument(
            id_=hashlib.sha256(
                f"{data['user_id']}-{data['folder_id']}-{data['note_id']}-overview".encode()
            ).hexdigest(),
            text=overall_summary,
            metadata=_base_metadata(chunk_id=0, summary=overall_summary),
            excluded_embed_metadata_keys=_EXCLUDED_EMBED,
            excluded_llm_metadata_keys=_EXCLUDED_LLM,
            metadata_template="{key}: {value}",
            text_template="Context Information:\n{metadata_str}\n\n---\nDocument Content:\n{content}\n",
        )
        llama_docs.insert(0, overview_doc)

    return doc_id, llama_docs


if __name__ == "__main__":
    text="""
It was late summer and the last hot sun of the season had the neighborhood bustling with activity.

Inspector Winston, a Dachshund with a talent for solving mysteries, was lying comfortably on a warm wooden bench near the garden wall. From here, he had a perfect view of both the house and the street so he could pick up a few exciting bits of conversation from the passers-by while making sure he didn’t miss any activity in the kitchen. His family was planning a barbecue for that night. 

“The last barbecue of the season!” said his dad sadly. All Winston could think about was the chance that a piece of sausage might accidentally fall to the ground for him to clean up. 
    """
    extract_keywords(text)