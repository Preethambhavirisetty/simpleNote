# Keyword and Entity Extraction Strategy

Keyword and entity extraction use separate paths so failure or noise in one path does not block the other.

## Keyword Path

1. Normalize chunk text locally. Markdown tables become deterministic header-value rows; raw pipe syntax is never sent to the model.
2. Skip keyword extraction for configured short chunks and non-text structural chunks.
3. Prepend `heading_context` when available unless content already starts with a Markdown heading.
4. Build batches constrained by both chunk count and token count.
5. Truncate only the prepared extraction copy of an oversized chunk. The request item includes `"truncated": true`; original chunk content is unchanged.
6. Call the `summarizer` model through `llm_call_general` with temperature `0`.
7. Retry a failed batch once. When a valid partial response omits chunk IDs, make one recovery call containing only the missing chunks. A permanently failed or missing chunk receives an empty keyword list.
8. Rank candidates by distinct heading section so semantic child chunks do not inflate repeated heading terms, then make the final keyword deduplication LLM call.

Batch settings:

- `KEYWORD_EXTRACTION_MAX_CHUNKS`: Maximum chunks per request. Default `10`.
- `KEYWORD_EXTRACTION_MAX_TOKENS`: Maximum combined prepared-text tokens per request. Default `3000`.
- `KEYWORD_EXTRACTION_CONCURRENCY`: Concurrent requests within one document, clamped to `3`. Default `1`.

The output token budget is calculated per batch as `min(batch_size * 80, 1200)`.

## Entity Path

Entities are extracted locally with spaCy from normalized text, independently of keyword LLM calls. Eligible chunks are processed together with `nlp.pipe` to avoid per-chunk pipeline overhead. Short chunks remain eligible.

Obvious table-header fusions, fragmented OCR spans, and generic infrastructure abbreviations are removed locally. Final entity validation receives spaCy labels and short source-context examples.

Allowed spaCy labels:

- `PERSON`
- `ORG`
- `GPE`
- `LOC`
- `PRODUCT`

Code, JSON, and heading-only chunks are excluded. Extracted candidates are ranked across chunks and passed through the final entity validation/deduplication LLM call.

## Events and Accounting

Events record stage summaries, batch completions/retries/failures, truncation, and skipped keyword chunks. Successful per-chunk extraction is not logged.

API-call accounting separates:

- `keyword_extraction`
- `keyword_extraction_retries`
- `keyword_dedup`
- `entity_dedup`
