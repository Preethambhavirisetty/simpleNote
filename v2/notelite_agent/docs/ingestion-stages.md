# Ingestion Stages

## 1. ChunkProcessor

- **Input:** Raw note text
- **Output:** `list[TextChunk]`
- **Next:** `KeywordProcessor.process()`
- **Purpose:** Structural splitting, semantic splitting, chunk classification, heading metadata, and final size normalization.

```python
chunks = chunk_processor.process(text)
```

## 2. KeywordProcessor

- **Input:** `list[TextChunk]`
- **Output:** `list[ChunkKeywordResult]`, top keywords, and entities
- **Next:** `ChunkBuilder.build()`
- **Purpose:** Batched LLM keyword extraction, spaCy entity extraction, ranking, and final deduplication.

```python
chunks_with_terms, top_keywords, entities = keyword_processor.process(chunks)
```

## 3. ChunkBuilder

- **Input:** `list[ChunkKeywordResult]`
- **Output:** `list[IndexChunk]`
- **Next:** `QdrantVectorStore.replace_index_chunks()`
- **Purpose:** Build `embed_text`, skip flags, complete previous/next links, and index metadata.
- **Skip:** `skip_indexing=True` chunks remain in the artifact list but are not currently persisted to PostgreSQL or Qdrant.

```python
def build_embed_text(chunk) -> str: ...
def augment_table_chunk(chunk) -> str: ...
def build_index_chunks(chunks) -> list[IndexChunk]: ...
```

Tables embed only deterministic natural-language descriptions. Code, JSON, heading-only, OCR-flagged, and below-threshold chunks can be skipped from indexing.

## 4. Chunk Embedding and Indexing

- **Input:** Indexable `list[IndexChunk]`
- **Output:** Chunk vectors in `QDRANT_COLLECTION`
- **Next:** `SummarizationPipeline.run()`
- **Purpose:** Embed `IndexChunk.embed_text` and store original `content` with retrieval metadata.

```python
vector_store.replace_index_chunks(document_id, index_chunks)
```

## 5. SummarizationPipeline

- **Input:** Complete `list[IndexChunk]`
- **Output:** `DocumentSummary`
- **Next:** `SummaryBuilder.build()`
- **Purpose:** Hierarchically summarize eligible `embed_text` values, then generate questions separately.
- **Skip:** Heading-only, code, JSON, OCR-flagged, empty, and below-threshold chunks.

```python
document_summary = summarization_pipeline.run(index_chunks)
```

## 6. SummaryBuilder

- **Input:** `DocumentSummary` plus document keywords/entities
- **Output:** `SummaryArtifacts` containing one optional `SummaryDocument` and multiple `QuestionDocument` objects
- **Next:** `QdrantVectorStore.upsert_summary_artifacts()`
- **Purpose:** Build vendor-neutral summary and question artifacts with stable IDs and embedding text.

```python
summary_artifacts = summary_builder.build(document_summary)
```

## 7. Summary and Question Indexing

- **Input:** `SummaryArtifacts`
- **Output:** Summary and question vectors
- **Collections:** `QDRANT_COLLECTION + "_summaries"` and `QDRANT_COLLECTION + "_questions"`
- **Purpose:** Embed the summary once and each generated question independently.

```python
vector_store.upsert_summary_artifacts(summary_artifacts)
```

## Current Pipeline

```text
text
  -> chunks
  -> keywords/entities
  -> IndexChunk artifacts
  -> chunk vectors
  -> DocumentSummary
  -> summary/question artifacts
  -> summary and question vectors
```
