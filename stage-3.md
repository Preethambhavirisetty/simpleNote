### New flow:
1. Chunking
2. KW / Entity extraction
3. DocumentBuilder          ← current, last stage before chunk embedding
4. Chunk embedding
5. Chunk indexing → notelite_chunks

6. Hierarchical summarization
7. Question generation
8. Summary embedding
9. Summary indexing → notelite_summaries
10. Question embedding
11. Question indexing → notelite_questions

## DocumentBuilder — What It Is

DocumentBuilder is the assembly stage that takes raw `TextChunk` objects from the chunker and produces `IndexChunk` objects ready for embedding and indexing. DocumentBuilder is the last stage before chunk embedding and chunk indexing. Every decision about what gets embedded, how it gets embedded, and what gets skipped happens here.


---

## Core Responsibility

For each chunk, DocumentBuilder answers three questions:

**What text gets embedded?** Not always `content` verbatim. Tables need augmented NL descriptions. Code chunks may not be embedded at all. Heading-only chunks under a token threshold get skipped. The `embed_text` field is what you pass to BAAI/bge-m3 — it must be the highest quality semantic representation of the chunk, not raw content.

**Does this chunk get indexed?** Some chunks have no retrieval value. Heading-only chunks with no body content, OCR garbage chunks, pure boilerplate — these should be skipped from Qdrant but preserved in PostgreSQL for document reconstruction.

**What is this chunk's position in the document?** DocumentBuilder has the full ordered list of all chunks for a document. It is the only stage that can compute `prev_chunk_id` and `next_chunk_id`. These links enable context expansion at query time without a second vector search.

---

## embed_text Construction by Chunk Type

This is the most important logic in DocumentBuilder. Wrong embed_text means wrong embeddings means wrong retrieval — everything downstream fails silently.

**content** — Check if content already starts with a markdown heading. If yes, use content as-is. If no, prepend `heading_context + "\n\n" + content`. Never double-prepend. Your `has_heading_context` flag is the guard here.

**table** — Never embed raw pipe-delimited content. Use your deterministic NL augmentation output. Format: `"{heading_context}\n\n{nl_description}"`. The nl_description comes from your table augmentation step which runs before DocumentBuilder.

**faq** — Content as-is. FAQ content is already structured for retrieval — the Q: A: format is semantically rich and the embedding model handles it well without modification.

**glossary** — Content as-is. Same reasoning as FAQ — the `TERM — definition` format is clean.

**code / json** — Two options depending on your preference. Either skip indexing entirely (`skip_indexing: true`) since code is rarely what users search for in a notes app, or embed only the heading context without the code body. For a personal notes app skipping is usually correct — users search for concepts not syntax.

**quote** — Prepend heading context. Quote content is often short and decontextualized — the heading tells the embedding model what the quote is about.

**transcript** — Prepend heading context. Speaker turns without context embed poorly.

**heading_only** — Skip indexing if token count is below a threshold (suggested: 20 tokens). These chunks exist for document structure preservation, not retrieval. If above threshold, embed heading context only.

**contact / address** — Embed as-is. Users search for people and places by name — these chunks have high retrieval value without modification.

**list / structured_list** — Prepend heading context. List items without context lose their meaning.

---

## skip_indexing Decision Logic

```
skip if chunk_type == heading_only AND token_count < 20
skip if chunk_type == code (personal notes app — adjust if your users paste code)
skip if chunk_type == json
skip if skip_keywords == true AND chunk_type == content (OCR garbage)
skip if token_count < 10 (too short to embed meaningfully)
```

Always set `skip_reason` when skipping. You will need this for debugging retrieval gaps later.

**Never delete skipped chunks from PostgreSQL.** They are needed for document reconstruction, re-ingestion, and debugging. Skip means skip from Qdrant only.

---

## prev_chunk_id and next_chunk_id

Compute these after processing all chunks for a document, not during individual chunk processing. Simple pass over the ordered chunk list:

```
for i, chunk in enumerate(chunks):
    chunk.prev_chunk_id = chunks[i-1].chunk_id if i > 0 else None
    chunk.next_chunk_id = chunks[i+1].chunk_id if i < len-1 else None
```

Skip-indexed chunks still get these links. At query time when you retrieve chunk N and want context expansion, you may want to fetch N-1 even if N-1 is heading_only — it tells you what section you are in.

---

## Edge Cases You Must Handle

**Heading context duplication** — Content that starts with `## My Section\n\nBody text` already has the heading. If you prepend `heading_context` which also contains `My Section`, the embedding sees that phrase twice and over-weights it. Check `content.strip().startswith("#")` before prepending.

**Empty embed_text after processing** — Table augmentation might return empty for a malformed table. Code stripping might leave nothing. Always validate `embed_text` is non-empty before passing to embedding. If empty after processing, fall back to `heading_context` alone. If heading_context is also empty, skip the chunk.

**Token count of embed_text exceeds embedding model limit** — BAAI/bge-m3 supports 8192 tokens but your chunks are 512. After prepending heading_context you might exceed 512 on some chunks. Decide your policy: truncate embed_text to 512 tokens, or allow up to 1024 for chunks where context is critical. Truncation should always cut from the end, never the beginning — the most important semantic content is usually at the start.

**Consecutive skip-indexed chunks** — If chunks 3, 4, 5 are all skipped, chunk 2's `next_chunk_id` should still point to chunk 3 even though it is skipped. At query time your context expansion logic needs to know to step over skipped chunks when fetching context. Add a `skip_indexing` flag to the link payload so the query layer knows what it is fetching.

**Document with all chunks skipped** — Rare but possible if someone uploads a pure code file or OCR garbage. Detect this before embedding runs and mark the document as `index_status: skipped` in PostgreSQL. Do not create empty collections entries.

**Re-ingestion of existing document** — User updates a note. You need to delete all existing Qdrant vectors for that document before re-indexing. Use `doc_id` as the payload filter for bulk delete. DocumentBuilder should receive a `reingestion: true` flag so it knows to trigger the delete step before indexing new chunks.

---

## Best Practices for Good Retrieval

**embed_text quality is everything.** Spend time getting the embed_text construction right by chunk type. A poorly constructed embed_text produces a vector that is close to the wrong things in embedding space. No amount of retrieval tuning fixes bad embeddings.

**Preserve semantic completeness in each chunk.** A chunk that starts mid-sentence or ends mid-thought embeds poorly. If your chunker produces boundary fragments (which yours sometimes does — chunks 4 and 5 in the incident log), DocumentBuilder should detect very short fragments (under 30 tokens) and consider merging them into adjacent chunks. Short fragments produce weak embeddings that hover near the centroid of the embedding space rather than a specific semantic region.

**heading_context is your single biggest retrieval quality lever for structured documents.** A chunk about `"Reciprocal Rank Fusion"` under heading `"Retrieval Pipeline > Hybrid Search Architecture"` embeds near retrieval-related queries. The same chunk without heading context embeds near generic algorithm discussions. Always prepend for non-FAQ, non-glossary chunks.

**For personal notes (no headings), embed_text is just content.** Most user journal entries have no headings. `has_heading_context: false` means you are embedding raw prose. This is fine — BAAI/bge-m3 handles unstructured personal writing well. Do not invent fake heading context for unstructured notes.

**Normalize whitespace in embed_text.** Strip leading/trailing whitespace, collapse multiple blank lines to one, remove markdown formatting artifacts (`**`, `*`, `__`) before embedding. These characters add noise to the embedding without semantic value.

**Store embed_text in PostgreSQL alongside content.** Not in Qdrant payload — Qdrant payload should be lean (chunk_id, doc_id, chunk_type, heading_context, token_count). Store the full embed_text in PostgreSQL so you can audit what was actually embedded when debugging retrieval issues. You will need this.

**Index creation order matters.** Create your HNSW index after bulk insertion, not before. Qdrant builds a better graph when it sees the full collection than when it updates the graph incrementally for each insert. For initial ingestion use `upload_collection` in batch mode. For subsequent single-document ingestion, incremental upsert is fine.

---

## IndexChunk Schema — Final

```json
{
    "chunk_id": "",
    "document_id": "",
    "chunk_index": 0,
    "total_chunks": 0,
    "chunk_type": "",
    "content": "",
    "embed_text": "",
    "skip_indexing": false,
    "skip_reason": "",
    "prev_chunk_id": "",
    "next_chunk_id": "",
    "keywords": [],
    "entities": [],
    "metadata": {
        "h1": "",
        "h2": "",
        "h3": "",
        "h4": "",
        "heading_context": "",
        "has_heading_context": false,
        "token_count": 0,
        "char_count": 0,
        "embed_text_token_count": 0,
        "language": "en",
        "embedding_model": "",
        "embedding_dim": 0,
        "indexed_at": ""
    }
}
```

`embed_text_token_count` is separate from `token_count` — the original chunk token count and the final embed_text token count differ whenever you prepend heading context. Track both so you can monitor how much heading context is inflating your embedding inputs.