"""Document assembly — orchestrates the full ingestion pipeline.

Calls chunking, keyword extraction, LLM enrichment stages, then
assembles LlamaDocument objects ready for vector store upsert.
"""

import hashlib
import time
from collections import Counter

import structlog
from llama_index.core import Document as LlamaDocument

from pipeline.chunking import split_into_sections
from pipeline.keywords import extract_keywords
from pipeline.enrichment import (
    recursive_summarize,
    deduplicate_keywords_llm,
    generate_questions,
)

log = structlog.get_logger()

_TOP_N_KEYWORDS = 15


def _shared_metadata(data: dict, doc_id: str) -> dict:
    return {
        "doc_id": doc_id,
        "user_id": data["user_id"],
        "tenant_id": data.get("tenant_id"),
        "folder_id": data["folder_id"],
        "note_id": data["note_id"],
        "folder_title": data["folder_title"],
        "note_title": data["note_title"],
        "description": data["description"],
        "tags": ",".join(data["tags"]),
    }


def get_document_objects(data: dict) -> tuple[str, LlamaDocument | None, list[LlamaDocument]]:
    """Run the full ingestion pipeline and return (doc_id, summary_doc, chunk_docs).

    Pipeline stages:
        1. Chunking — structural + semantic text splitting
        2. Keyword/entity extraction per chunk
        3. Keyword deduplication via LLM
        4. Recursive summarization
        5. Question generation from summary
        6. LlamaDocument assembly
    """
    if "text" not in data:
        raise ValueError("provide text to get chunks")

    pipeline_start = time.monotonic()
    full_text = data["text"]
    doc_id = f"{data['user_id']}-{data['folder_id']}-{data['note_id']}"

    # ── 1. Chunking ──────────────────────────────────────────────────────
    chunks = split_into_sections(full_text)
    log.info("pipeline.chunking", chunk_count=len(chunks), doc_id=doc_id)

    # ── 2. Keyword + entity extraction per chunk ─────────────────────────
    chunk_results = [extract_keywords(c, _TOP_N_KEYWORDS) for c in chunks]
    chunk_keywords = [kws for kws, _ in chunk_results]
    chunk_entities = [ents for _, ents in chunk_results]

    all_keywords = [kw for kws in chunk_keywords for kw in kws]
    keywords_counter = Counter(all_keywords)
    filtered_keywords = [
        (kw, count) for kw, count in keywords_counter.items()
        if count >= 2 or len(kw.split()) >= 2
    ]
    sorted_keywords = [
        kw for (kw, _) in sorted(filtered_keywords, key=lambda x: x[1], reverse=True)[:40]
    ]
    all_entities = list(dict.fromkeys(ent for ents in chunk_entities for ent in ents))

    # ── 3. Keyword deduplication via LLM ─────────────────────────────────
    top_keywords = deduplicate_keywords_llm(sorted_keywords) if sorted_keywords else []
    log.info("pipeline.keyword_dedup", keyword_count=len(top_keywords), doc_id=doc_id)

    # ── 4. Recursive summarization ───────────────────────────────────────
    overall_summary = recursive_summarize(chunks)

    # ── 5. Question generation ───────────────────────────────────────────
    global_questions = generate_questions(overall_summary) if overall_summary else []
    log.info("pipeline.questions", question_count=len(global_questions), doc_id=doc_id)

    # ── 6. Build documents ───────────────────────────────────────────────

    summary_doc = None
    if overall_summary:
        summary_meta = _shared_metadata(data, doc_id)
        summary_meta["keywords"] = [
            kw.strip()
            for line in top_keywords
            for kw in line.split(",")
            if kw.strip()
        ]
        summary_meta["entities"] = all_entities
        summary_meta["questions"] = global_questions

        summary_doc = LlamaDocument(
            id_=hashlib.sha256(f"{doc_id}-summary".encode()).hexdigest(),
            text=overall_summary,
            metadata=summary_meta,
        )

    _EXCLUDED_EMBED = ["user_id", "folder_id", "note_id", "chunk_id", "parent_summary"]
    _EXCLUDED_LLM = ["user_id", "folder_id", "note_id", "chunk_id"]

    chunk_docs = []
    for idx, chunk in enumerate(chunks, start=1):
        meta = _shared_metadata(data, doc_id)
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

    total_latency_ms = int((time.monotonic() - pipeline_start) * 1000)
    log.info(
        "pipeline.complete",
        doc_id=doc_id,
        chunk_count=len(chunk_docs),
        keyword_count=len(top_keywords),
        entity_count=len(all_entities),
        has_summary=bool(summary_doc),
        question_count=len(global_questions),
        total_latency_ms=total_latency_ms,
    )
    return doc_id, summary_doc, chunk_docs
