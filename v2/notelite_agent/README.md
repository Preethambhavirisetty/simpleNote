# Notelite Agent — v2

FastAPI service that provides AI-powered ingestion and retrieval for the Notelite note-taking app.
Models (LLM + embedding) are hosted on a RunPod GPU container. This service runs on EC2 (CPU-only).

---

## Architecture overview

```
Backend (NestJS)
      │
      │  HTTP  (X-API-Key)
      ▼
┌─────────────────────────────────────────────────────────────┐
│  Notelite Agent  (FastAPI · EC2)                            │
│                                                             │
│  POST /api/ingest/   ──►  Celery Worker  ──► IngestionOrchestrator │
│                                                             │
│  POST /api/chat/completions  ──► (chat pipeline — WIP)     │
└──────────────────┬──────────────────────────────────────────┘
                   │
        ┌──────────┴──────────┐
        ▼                     ▼
  Qdrant (vectors)      PostgreSQL (version guard)
        │
        ▼
  RunPod (GPU container)
   ├─ Embedding model  :8000/embed   &  :8000/v1/embeddings
   ├─ LLM (Mistral)    :8001/chat/completions
   └─ LLM (Llama)      :8002/chat/completions
```

---

## Running locally

```bash
# API server
uvicorn app.main:app --port 3002

# Redis (message broker)
docker run -d -p 6379:6379 redis

# Celery ingestion worker
celery -A app.services.ingestion.workers.celery_app:celery_app worker \
  -l info -Q ingestion -P solo
```

---

## API

All endpoints return the same envelope:

```jsonc
// Success
{ "success": true,  "data": { ... } }

// Failure
{ "success": false, "error": "human-readable message" }
```

HTTP status codes are standard: `200`, `400`, `422`, `503`, `500`.

---

### `GET /health`

Service liveness probe.

**Response `data`**
```json
{ "status": "ok" }
```

---

### `GET /api/ingest/health`

Checks PostgreSQL and Qdrant connectivity.

**Response `data`**
```json
{
  "postgresql": "active",
  "qdrant":     "active"
}
```

---

### `POST /api/ingest/`

Ingest or delete a note. All fields except `action` are required for upserts.

**Request body**
```jsonc
{
  "user_id":      "uuid",
  "folder_id":    "uuid",
  "note_id":      "uuid",
  "note_title":   "string",
  "folder_title": "string",
  "description":  "string",        // optional
  "tags":         ["string"],      // optional
  "text":         "full note text",
  "action":       "upsert"         // or "delete" — defaults to "upsert"
}
```

**Response `data` — upsert**
```jsonc
{
  "action":       "upsert",
  "status":       "processed",
  "note_id":      "uuid",
  "text_tokens":  1234,            // tiktoken count of the input text
  "chunk_count":  18,
  "top_keywords": ["keyword", "..."],
  "entities":     ["Entity", "..."],
  "summary":      "One-paragraph summary of the note.",
  "questions":    ["Question?", "..."],  // 5 retrieval-optimised questions
  "api_calls": {
    "keyword_dedup": 2,
    "summary":       1,
    "questions":     1,
    "total":         4
  },
  "stages_ms": {
    "chunking":           45.2,
    "keyword_extraction": 310.8,
    "summary":            980.1,
    "questions":          420.3,
    "document_build":     12.4,
    "document_ingestion": 890.5,
    "total":              2659.3
  },
  "events": [
    "ingestion started",
    "document id created",
    "chunking completed: 18 chunks",
    "keywords started: 18 chunks",
    "keywords completed: 12 top keywords, 7 entities",
    "summary started: 18 chunks, 1234 tokens",
    "summary api call: direct",
    "summary completed: direct",
    "questions started",
    "questions api call",
    "questions completed: 5 generated",
    "documents build started",
    "summary document built",
    "chunk documents built: 18",
    "documents build completed: 1 summary, 18 chunks",
    "vector ingestion started",
    "document vectors deleted: user1-folder1-note1",
    "summary vector upserted",
    "chunk vectors upserted: 18",
    "vector ingestion completed",
    "ingestion completed"
  ]
}
```

**Response `data` — delete**
```jsonc
{
  "action":  "delete",
  "status":  "deleted",
  "doc_id":  "user1-folder1-note1",
  "note_id": "uuid"
}
```

---

### `GET /api/ingest/status/{job_id}`

Poll the status of a background Celery ingestion task.

**Response `data`**
```jsonc
{
  "job_id":  "celery-task-uuid",
  "status":  "PENDING" | "STARTED" | "SUCCESS" | "FAILURE",
  "result":  { ... } | null   // populated only when status is SUCCESS/FAILURE
}
```

---

### `POST /api/chat/completions`

Pass-through LLM completion (retrieval pipeline not yet wired).

**Request body**
```json
{
  "messages": [
    { "role": "system", "content": "You are a helpful assistant." },
    { "role": "user",   "content": "What is RAG?" }
  ]
}
```

**Response `data`**
```json
{ "response": "RAG stands for Retrieval-Augmented Generation..." }
```

---

### `POST /api/chat/stream`

Streaming chat — returns `501 Not Implemented` until the chat pipeline is built.

---

## Ingestion pipeline

```
Text (from request body)
        │
        ▼
┌─────────────────────────────────────────────┐
│  Three-tier Chunker                         │
│  1. Paragraphs  split on \n\n               │
│  2. Headings    regex: short capitalised    │
│  3. Semantic    SemanticSplitterNodeParser  │
│     (RunPod embedding model, batched)       │
│  4. Window      hard token-budget fallback  │
│  5. Post-process  heading/list cleanup      │
└────────────────────┬────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────┐
│  Keyword & Entity Extraction                │
│  spaCy NER  +  YAKE keyword scores          │
│  LLM dedup pass  (separate prompts for      │
│  keywords vs. named entities)               │
└────────────────────┬────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────┐
│  Hierarchical Summarisation                 │
│  ≤3 000 tok → single LLM call              │
│   > 3 000 tok → group summaries → merge    │
└────────────────────┬────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────┐
│  Question Generation                        │
│  5 retrieval-optimised questions from       │
│  the final summary                          │
└────────────────────┬────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────┐
│  Document Builder                           │
│  1 summary doc  +  N chunk docs             │
│  SHA-256 deterministic IDs (idempotent)     │
└────────────────────┬────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────┐
│  Qdrant Upsert (hybrid index)               │
│  dense vector   (RunPod /v1/embeddings)     │
│  sparse vector  (RunPod /embed, IDF)        │
│  questions vector  (summary collection only)│
│  delete-then-insert for clean replace       │
└─────────────────────────────────────────────┘
```

### Collections

| Collection | Contains | Vectors |
|---|---|---|
| `{QDRANT_COLLECTION}` | One point per chunk | `dense`, `sparse` |
| `{QDRANT_COLLECTION}_summaries` | One point per note | `dense`, `sparse`, `questions` |

### Payload schema (per Qdrant point)

```jsonc
{
  "text": "chunk or summary text",
  "keywords": ["term", "..."],
  "entities":  ["Entity", "..."],
  "created_at": 1716000000,
  "metadata": {
    "doc_id":       "user-folder-note",
    "user_id":      "uuid",
    "folder_id":    "uuid",
    "note_id":      "uuid",
    "note_title":   "string",
    "folder_title": "string",
    "tags":         "tag1,tag2",
    "chunk_id":     "0"          // chunks only
  }
}
```

---

## Embedding adapter — why it exists and is it optimal?

`RemoteOpenAIEmbedding` is a thin `BaseEmbedding` subclass required because
`SemanticSplitterNodeParser` (used in three-tier chunking) demands a LlamaIndex
`BaseEmbedding` instance assigned to `Settings.embed_model`.

**Performance:** the adapter is batching-optimal. `SemanticSplitterNodeParser`
calls `get_text_embedding_batch(all_sentences)` which routes to
`_get_text_embeddings(texts)` — a single HTTP POST to RunPod regardless of
how many sentences the document has. There is no per-sentence HTTP call.

`SharedEmbeddingClient` (used for ingestion and retrieval) calls the remote
service directly and never touches `Settings.embed_model`, so there is no
double-wrapping.

---

## Events — replayable trace

Every processor accumulates a plain string `events` list during its run.
The orchestrator merges all of them into a single ordered list returned in
the API response. This gives you a full deterministic trace of what happened:
which path was taken in the chunker, whether the LLM dedup call succeeded,
whether the summary was direct or hierarchical, etc.

Structured log entries (via `structlog`) are also emitted at each stage;
the `events` list in the response is an additional human-readable replay aid.

---

## Stage timing and token counting

**Stage timing** (`stages_ms` in response) measures wall-clock time from the
end of the previous stage to the end of the current one. This is the right
granularity for identifying bottlenecks.

**Token counting** uses `tiktoken cl100k_base` (OpenAI-compatible approximation):
- `text_tokens` in the response = input text size
- Used internally for chunking budget decisions (window size, overlap)
- Used for deciding direct vs. hierarchical summarisation

**LLM token usage** (prompt + completion tokens) is available from the RunPod
API response (`usage` field). It is currently logged at `DEBUG` level in
`shared/llm.py` but not surfaced in the API response. Add it when you need
per-request cost tracking.

---

## Known issues

- `replace_document` is not atomic: delete + insert has a brief window where
  the note has no vectors. Acceptable for now; use a transaction-aware upsert
  pattern when you need zero-downtime updates.
- No API key enforcement yet (`AGENT_API_KEY` is validated but auth is opt-in
  — set it to a non-empty value in `.env` to enforce it).
- The Celery `ingest_in_background` task is defined but the route currently
  runs synchronously in the request handler. Wire the task when you move to
  async ingestion.

---

## Chat pipeline — design (not yet implemented)

### Endpoint plan

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/chat/message` | Non-streaming RAG chat |
| `POST` | `/api/chat/stream` | Server-Sent Events streaming RAG chat |
| `GET` | `/api/chat/history/{conversation_id}` | Fetch message history |

---

### `POST /api/chat/message`

**Request body**
```jsonc
{
  "user_id":         "uuid",
  "conversation_id": "uuid | null",   // null → start new conversation
  "message":         "user question",
  "scope": {
    "folder_ids": ["uuid"],           // limit retrieval to these folders
    "note_ids":   ["uuid"]            // or specific notes; both optional
  },
  "options": {
    "stream":             false,
    "max_context_chunks": 5,          // default 5
    "include_summaries":  true        // also search summary collection
  }
}
```

**Response `data`**
```jsonc
{
  "conversation_id": "uuid",
  "message_id":      "uuid",
  "response":        "Generated answer text.",
  "sources": [
    {
      "note_id":    "uuid",
      "note_title": "string",
      "chunk":      "verbatim chunk text used as context",
      "score":      0.89
    }
  ],
  "debug": {
    "intent":           "retrieval",   // "retrieval" | "aggregation" | "general"
    "query_rewritten":  false,
    "chunks_retrieved": 10,
    "chunks_after_rerank": 5,
    "latency_ms":       1340
  }
}
```

---

### `POST /api/chat/stream`

Same request body as above with `"stream": true`.
Response is `text/event-stream` SSE:

```
data: {"delta": "Generated "}
data: {"delta": "answer "}
data: {"delta": "text."}
data: {"done": true, "message_id": "uuid", "sources": [...]}
```

---

### Chat pipeline stages

```
User message
      │
      ▼
Intent classifier  (lightweight: keyword rules + optional LLM)
      │
      ├── "general"      → skip retrieval, call LLM directly
      ├── "aggregation"  → search summary collection only
      └── "retrieval"    → full hybrid retrieval pipeline
                │
                ▼
      [Optional] Query rewriter  (LLM expands/rephrases query)
                │
                ▼
      Hybrid retrieval  (Qdrant RRF: dense + sparse)
      filtered by user_id + scope (folder_ids / note_ids)
                │
                ▼
      Cross-encoder reranker  (top-K final selection)
                │
                ▼
      Context builder  (format chunks + note metadata into prompt)
                │
                ▼
      LLM generation  (RunPod Llama or Mistral)
      │                   streaming → SSE
      │                   non-streaming → JSON
      ▼
      Message persistence  (Celery task → backend API)
```

### Key design notes

- **Tenant isolation:** every Qdrant query filters on `metadata.user_id`. The
  backend must pass a validated `user_id` — the agent trusts it.
- **Conversation memory:** full history is fetched from the backend (`pg_store`)
  before building the prompt. Token budget is enforced; oldest messages are
  truncated first.
- **Source attribution:** each returned source maps back to a `note_id` so the
  frontend can deep-link into the note.
- **Streaming persistence:** the response is streamed to the client immediately;
  a Celery `persist_message` task saves the full assembled text to the backend
  once streaming completes.

---

## Production readiness: 6 / 10

**What's solid**

| Area | Notes |
|---|---|
| Chunking | Three-tier strategy is robust; semantic splitting adds real quality |
| Hybrid vectors | Qdrant native RRF fusion (dense + sparse) in a single query |
| Summary + questions | Expands retrieval surface significantly |
| Hierarchical summarisation | Handles large documents without truncation |
| Keyword/entity extraction | Two-pass (local + LLM dedup) with correct separate prompts |
| Stage timing | Per-stage ms in every response; easy to spot bottlenecks |
| Worker | Celery with retries, backoff, dead-letter semantics |
| Events trace | Full deterministic replay of each pipeline run |

**What's missing before production**

| Gap | Priority |
|---|---|
| Auth not enforced | `require_api_key` is wired but `AGENT_API_KEY` defaults to empty → all requests pass | High |
| Celery not used | Route calls orchestrator synchronously; long notes block the request thread | High |
| No idempotency window | Delete+insert has a brief gap; use upsert-by-ID once Qdrant supports it | Medium |
| No test suite | Chunking regressions, tenant isolation, idempotent upsert all need golden tests | Medium |
| LLM token cost not surfaced | `usage` is logged at DEBUG but not in response; needed for cost tracking | Medium |
| No rate limiting | A single large note can saturate the LLM endpoint | Medium |
| `version` guard unused | `is_stale_ingestion` is never called from the route | Low |
| Observability | No metrics endpoint; no distributed tracing; structlog only | Low |
