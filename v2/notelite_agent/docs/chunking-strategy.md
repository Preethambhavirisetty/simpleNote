# Chunking Strategy

## Purpose

The chunking pipeline converts note and document text into ordered, typed, retrieval-ready chunks. Its primary goal is to preserve meaningful document structure before applying semantic or token-based splitting.

The strategy is intentionally hybrid:

1. Normalize obvious extraction artifacts.
2. Detect strong structural boundaries.
3. Classify chunks by content shape.
4. Semantically split only substantial prose.
5. Preserve and attach heading context.
6. Finalize stable ordering and size metadata.
7. Build a separate index-ready artifact with embedding-specific text.

Structural boundaries are stronger than semantic similarity. A semantic splitter must not merge content across headings, tables, code blocks, JSON blocks, or explicit dividers.

## Active Pipeline

The active pipeline is implemented in:

- `chunk_classifier.py`: structural splitting and chunk type classification orchestration.
- `chunk_type_rules.py`: type-specific classification predicates.
- `chunk_types.py`: supported chunk types and ordered rule table.
- `chunk_processor.py`: semantic prose splitting, heading metadata, compatible merges, and final ordering.
- `semantic_chunker.py`: bounded semantic splitting with a local fallback.
- `window_chunker.py`: sentence-aware, table-aware, and token-window size normalization.
- `document_builder.py`: index-ready artifact creation and embedding text preparation.
- `vector_store.py`: embedding and Qdrant payload creation.

Files under `chunking/deprecated/` are retained only for historical reference and are not part of the active strategy.

## Pipeline Stages

### 1. Text Normalization

`ChunkProcessor.process()` first repairs OCR/PDF word breaks such as:

```text
experi-
ence
```

into:

```text
experience
```

This normalization is deliberately narrow. It repairs clear OCR hyphenation without broadly rewriting whitespace or flattening document structure.

### 2. Whole-Document Classification Shortcuts

Before detailed structural splitting, the classifier checks whether the entire input is already an atomic unit.

Atomic unheaded documents such as an address, contact block, FAQ, glossary, JSON object, list, quote, or structured list remain one chunk. This avoids unnecessarily breaking a naturally cohesive block.

Plain unheaded content also remains one chunk when it contains no structural blocks or code-like paragraphs. Substantial prose may still be split later by the semantic stage.

### 3. Structural Block Detection

The splitter scans the document line by line and detects:

- Markdown headings: `#` through `######`.
- Fenced code blocks using backticks or tildes.
- Fenced JSON blocks.
- Pipe-delimited tables.
- Explicit divider lines.
- Ordinary prose paragraphs.

Strong structural blocks are emitted independently before semantic splitting.

#### Divider behavior

A line containing only at least three dashes, underscores, or asterisks is a divider:

```text
---
--------------------------------------------------
___
***
```

Dividers force a boundary flush but are consumed and never emitted as chunks. A divider after a pending heading does not discard that heading; the heading remains attached to the following content.

Text such as `--- PAGE BREAK ---` is not a pure divider and is treated as ordinary content.

#### Heading behavior

Markdown headings update structural context and establish section boundaries. Sibling or shallower headings close pending heading-only sections. Adjacent heading-only runs are merged while duplicate ancestor heading lines are removed.

Top-level and subsection headings remain stronger boundaries than semantic similarity. Content from separate headed sections is not merged simply because the text is similar.

Numbered list items are not Markdown headings and do not update heading context.

### 4. Chunk Type Classification

Classification uses an ordered rule table. Order matters because some content shapes overlap. For example, quote detection runs before glossary detection, and contact detection runs before address detection.

If no rule matches, the chunk type is `content`.

## Supported Chunk Types

### `content`

The default type for prose or any text that does not confidently match a more specific type. Only `content` chunks are candidates for semantic prose splitting.

Examples include paragraphs, reports, page markers, repeated notices, and ordinary mixed text.

### `heading_only`

A block containing only Markdown heading lines and no body content.

This type preserves empty sections and heading hierarchy instead of silently dropping them. Consecutive heading-only chunks are merged with duplicate shared ancestors removed.

### `table`

A block where most non-empty lines are pipe-delimited table rows and at least two data rows are present.

Tables are structural chunks. They are not semantically split as prose and the active `ChunkProcessor` does not currently split structural table chunks by size.

At document-build time, tables receive a natural-language summary in `embed_text` while original table content remains unchanged. The reusable `WindowChunker` includes table-row splitting support for callers that explicitly use its general size-normalization path.

### `code`

Fenced code blocks or sufficiently code-like unfenced command/code sequences.

Unfenced code requires multiple lines and a strong ratio of recognizable shell, Python, JavaScript, SQL, Dockerfile, assignment, or control-flow patterns. Code is kept structurally intact and is not passed through prose semantic splitting.

### `json`

Fenced JSON or an unfenced object/array with quoted JSON-like content.

JSON is kept structurally intact and is not passed through prose semantic splitting.

### `faq`

One or more balanced question-and-answer pairs using markers such as `Q:`, `Question:`, `A:`, or `Answer:`.

FAQ pairs remain grouped because splitting questions from their answers harms retrieval quality.

### `transcript`

Dialogue containing at least two distinct speakers. Supported forms include speaker labels, chat timestamps, and timestamped speaker labels.

Transcript detection is conservative to avoid classifying ordinary prose containing names or labels as dialogue. Transcript fragments may be grouped when the overall document is classified as a transcript.

### `address`

A physical address identified through street, locality/postal, or building signals. Address detection excludes contact blocks first.

### `contact`

A block containing an email address, phone number, or explicit contact label. Contact detection runs before address detection because contact blocks often contain address-like lines.

### `glossary`

A set of definition pairs such as `TERM: definition` or `TERM - definition`. FAQ content is explicitly excluded from glossary classification.

### `appendix`

A section beginning with an explicit appendix heading or marker.

### `quote`

Quoted statements or Markdown blockquotes, optionally followed by attribution lines. Quote detection runs before glossary detection because attribution punctuation can overlap with definition syntax.

### `list`

An unordered bullet or task list. Nested bullet lists remain together when possible.

### `structured_list`

An ordered or hierarchical list using Arabic numbers, decimal hierarchy, alphabetic markers, or Roman numerals.

## Types We Deliberately Do Not Use

There is no `footer` chunk type. Footer-like text, page markers, repeated confidentiality notices, and similar extracted text follow the ordinary content path.

Pure divider lines remain structural boundary signals, but they are not chunk types and do not produce output.

## Semantic Chunking

Semantic chunking is a post-processing step for `content` chunks only. Tables, code, JSON, and other structural chunk types are not semantically split.

Before semantic splitting, leading Markdown headings are removed from the prose passed to the semantic splitter. The heading prefix is reattached only to the first semantic part. This prevents remote or local sentence splitting from flattening a heading and its first prose sentence onto one line.

Semantic splitting is triggered only for sufficiently substantial prose:

- Short prose remains intact.
- Prose must contain enough sentences to justify a semantic call.
- The remote semantic splitter uses the configured embedding model and breakpoint percentile.
- Remote failures or timeouts activate a cooldown and fall back locally.

The local fallback groups sentences by a token target. Small trailing fragments are merged upward when they fit the configured chunk budget.

## Size Normalization

Chunk sizing uses token counts rather than character counts. Configuration is provided through:

- `MAX_CHUNK_SIZE`
- `CHUNK_OVERLAP`
- `BREAKPOINT_PERCENTILE`
- `SEMANTIC_CHUNKING_TIMEOUT`
- `SEMANTIC_CHUNKING_FAILURE_COOLDOWN`

For callers using the general `WindowChunker.split()` path, the fallback order is:

1. Keep the chunk if it already fits the token budget.
2. Preserve fenced code blocks.
3. Split oversized tables by rows while repeating useful header context.
4. Split prose by sentence boundaries.
5. Hard-split oversized single sentences by token window.

The active `ChunkProcessor` uses the semantic prose path only for `content` chunks. Its local semantic fallback uses no artificial overlap between final parts. Structural context and heading metadata provide context without duplicating arbitrary token windows.

## Compatible Post-Merges

After semantic splitting and classification, some adjacent chunks may be merged when they share the same heading context and remain within the chunk budget.

Compatible groups include:

- Address and contact chunks.
- Quote chunks.
- Ordered and unordered list chunks.
- Appendix-compatible content and lists.

These merges reduce tiny fragments while respecting section boundaries.

## Heading Context

Heading context is tracked from Markdown headings found in final chunk content.

When a heading at depth `N` appears:

- The context at depth `N` is updated.
- Deeper heading levels are cleared.
- Shallower parent levels remain active.

Heading titles are extracted from one physical line only. Semantic splitting never receives leading heading lines, which protects the heading/prose boundary.

Available heading levels are emitted dynamically. Missing levels are omitted rather than stored as empty strings.

Example metadata:

```json
{
  "h1": "Enterprise Data Platform",
  "h2": "Streaming Ingestion",
  "h3": "Apache Kafka Configuration",
  "heading_context": "Enterprise Data Platform > Streaming Ingestion > Apache Kafka Configuration",
  "has_heading_context": true
}
```

## Final Chunk Contract

After all splitting and compatible merges, `ChunkProcessor` assigns stable document-local ordering and cheap-to-compute metrics.

```json
{
  "content": "## Configuration\n\nThe timeout is 30 seconds.",
  "chunk_id": "4",
  "chunk_type": "content",
  "chunk_index": 4,
  "total_chunks": 12,
  "metadata": {
    "h1": "Operations Guide",
    "h2": "Configuration",
    "heading_context": "Operations Guide > Configuration",
    "has_heading_context": true,
    "token_count": 11,
    "char_count": 48
  }
}
```

### Field decisions

- `content`: Original final chunk text. It is the source of truth shown to users and downstream processors.
- `chunk_id`: Stable document-local identifier. It currently matches the zero-based final chunk index.
- `chunk_type`: Enables downstream behavior without reclassifying text.
- `chunk_index`: Explicit ordering for reconstruction and neighbor expansion.
- `total_chunks`: Allows consumers to understand document-level position without recomputing it.
- `h1` through deeper available heading levels: Preserves hierarchy for filtering and context.
- `heading_context`: Compact readable hierarchy for retrieval and embedding context.
- `has_heading_context`: Avoids repeated truthiness checks and distinguishes unheaded content explicitly.
- `token_count`: Used for prompt, retrieval, and chunk-budget decisions.
- `char_count`: Cheap diagnostic and operational metric.

All counts are calculated after final merges so they describe the actual emitted chunks.

## Index-Ready Artifact

`DocumentBuilder` converts chunk and keyword results into index-ready artifacts. This stage owns document identity, embedding text, and adjacency because it has the full ordered chunk list and note payload.

The artifact shape is:

```json
{
  "chunk_id": "4",
  "note_id": "note-id",
  "folder_id": "folder-id",
  "chunk_index": 4,
  "total_chunks": 12,
  "chunk_type": "content",
  "content": "## Configuration\n\nThe timeout is 30 seconds.",
  "embed_text": "Operations Guide > Configuration\n\nThe timeout is 30 seconds.",
  "skip_indexing": false,
  "skip_reason": "",
  "keywords": [],
  "entities": [],
  "metadata": {
    "heading_context": "Operations Guide > Configuration",
    "has_heading_context": true,
    "token_count": 11,
    "char_count": 48,
    "prev_chunk_id": "3",
    "next_chunk_id": "5"
  }
}
```

### `content` versus `embed_text`

`content` and `embed_text` serve different purposes:

- `content` preserves the original final chunk for retrieval context, display, keyword extraction, and summarization.
- `embed_text` is optimized for embedding and is the only text sent to the embedding service.

For normal headed content, `embed_text` is:

```text
heading_context

body without duplicated leading Markdown headings
```

For tables, `embed_text` contains a natural-language table description followed by the original table. This improves semantic retrieval without replacing or mutating the source table.

Separating the fields keeps the embedding stage stateless. It reads `embed_text` without needing to know how to reconstruct context from chunk type or metadata.

### Skip fields

The artifact contract includes `skip_indexing` and `skip_reason` for future structural or quality-based exclusions. There are currently no active skipped chunk types, so artifacts are presently indexable by default.

### Adjacent chunk references

`DocumentBuilder` assigns `prev_chunk_id` and `next_chunk_id` over the ordered indexable artifact list. Missing references are omitted for the first and last chunks.

These references support retrieval-time context expansion without performing another vector search. A retrieved chunk can directly identify its neighboring chunks in the same note.

## Vector Storage

The vector store embeds `embed_text` and stores original `content` in the Qdrant payload. Retrieval reconstructs documents using original `content`, not embedding-specific text.

Immediately before indexing, the vector store adds:

- `embedding_model`
- `embedding_dim`
- `indexed_at`

These values belong to the indexing stage because they are not known reliably during chunking or document building.

Identity fields such as `doc_id` and `user_id` remain in Qdrant metadata because existing filtering depends on paths such as `metadata.user_id` and `metadata.doc_id`.

## Downstream Type Behavior

Chunk type affects later ingestion stages:

- Keyword/entity extraction skips `heading_only`, `code`, and `json` chunks.
- Summarization skips structural or low-value types including `heading_only`, `code`, `json`, `address`, `contact`, `glossary`, `appendix`, and `quote`.
- All current chunk artifacts are indexable.

These downstream decisions are separate from splitting. A chunk can be useful for retrieval while intentionally excluded from summarization or keyword extraction.

## Regex Organization

Only reusable structural patterns should live in `patterns.py`. The divider pattern is shared and belongs there.

Classification-specific regexes remain beside their owning rules in `chunk_type_rules.py`. Keeping local patterns close to their behavior makes thresholds, exclusions, and rule interactions easier to understand than a single large global regex registry.

## Important Invariants

The active strategy should preserve these invariants:

- Never emit pure divider lines as chunks.
- Never merge content across explicit divider boundaries.
- Never merge content across different headed sections merely because it is semantically similar.
- Preserve heading-only sections without duplicating shared ancestor headings.
- Do not allow semantic splitting to consume heading lines.
- Do not treat numbered list items as Markdown heading context.
- Preserve tables, fenced code, and JSON as structural units.
- Compute ordering and size metadata only after final merges.
- Embed `embed_text`, but store and return original `content`.
- Compute adjacency only when the full ordered artifact list is available.

## Operational Events

`ChunkProcessor.events` is reset for every call and records concise stage activity. Events are returned by the standalone `ingestion.chunk` action and included in the orchestrator ingestion event list.

Typical events include:

- `chunking started: N tokens`
- `chunking structural split: N chunks`
- `semantic chunking completed: N parts`
- `semantic chunking failed: ErrorType; local fallback`
- `semantic chunking skipped: failure cooldown`
- `chunking semantic split: N source chunks; M total chunks`
- `chunking compatible merges: N`
- `chunking completed: N chunks`

Conditional events are emitted only when the corresponding work occurs. These events make semantic timeouts, local fallback, boundary splitting, and final chunk counts visible without changing chunk output.

## Testing

Primary coverage lives in:

- `app/services/tests/test_chunking.py`
- `app/services/tests/chunk_test_data_stress.py`
- `app/services/tests/test_index_artifacts.py`
- `app/services/ingestion/processors/keywords/test_keywords.py`

Changes to structural boundaries, chunk type rules, semantic behavior, metadata, embedding text, or index artifacts should include general regression cases. Tests should describe reusable behavior rather than special-case fixture names or exact production document strings.
