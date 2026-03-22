
Chunking:
structural split (paragraph/headings),
semantic split fallback,
hard size enforcement + overlap,
post-processing (heading/list parent-child cleanup).

ISSUES:
Performance hotspot: BM25 index(BM25Okapi) rebuilds across all docs on each upsert. Fine for now; at scale we should switch to incremental or scoped index rebuild.
Background ingestion is still sync placeholder (no real worker queue lifecycle yet).
No task status tracking/retries/DLQ semantics yet.
No robust observability (structured logs, metrics, traces).
No formal test suite for critical paths (RBAC, idempotency, chunking regressions).
Retrieval path still missing real LLM-answer integration + guardrails.


How the Architecture Works
BE sends request: Instead of calling a FastAPI URL directly, the BE pushes a JSON payload (containing the document or file path) into a queue like Redis, RabbitMQ, or AWS SQS.
RAG Worker listens: Your FastAPI service runs a background process (like Celery, RQ, or a native async loop) that "watches" the queue.
Processing: The worker pulls the message, uses LlamaIndex to chunk/embed the data, and pushes it to Qdrant.
Acknowledgment: Once finished, the worker marks the task as complete.


Minimum to call it production-grade (v1)
Real async ingestion worker (Celery/Redis Streams) with retries + DLQ.
Task state API (queued/running/succeeded/failed).
Test suite:
RBAC enforcement
idempotent upsert
chunking golden tests
tenant isolation
Observability:
request IDs, task IDs
ingest latency/chunk count/retrieval latency


BE - QUEUE - WORKER

uvicorn main:app --port 3002
QUEUE service: docker run -d -p 6379:6379 redis
celery -A apis.worker:worker_app worker -l info -Q ingestion -P solo
CELERY PROVIDES: retries, concurrency, rate limiting, visibility


# RAG Pipeline

A local, privacy-first Retrieval-Augmented Generation pipeline built from scratch. All models run locally via HuggingFace -- no API keys, no cloud dependencies, no cost.

## Architecture

```
Knowledge Files (.md, .txt)
        │
        ▼
┌─────────────────────┐
│   Three-Tier        │
│   Chunking          │
│  ┌───────────────┐  │
│  │ 1. Paragraphs │  │   Split on \n\n
│  │ 2. Headings   │  │   Regex: capitalized short lines
│  │ 3. Semantic   │  │   LlamaIndex SemanticSplitterNodeParser
│  └───────────────┘  │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│   Metadata          │   source, knowledge_type, chunk_index, is_summary
│   + Summary Chunks  │   One per file for aggregation queries
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│   Vector Store      │   Qdrant (default) or Chroma
│   (Persisted)       │   Swappable via .env config
└─────────┬───────────┘
          │
  ════════╪══════════════════════════════════
  QUERY   │  TIME
  ════════╪══════════════════════════════════
          │
          ▼
┌─────────────────────┐
│   Intent Processor  │   Detects knowledge domain + query type
│   (QueryProcessor)  │   Keyword match → Embedding similarity fallback
└─────────┬───────────┘
          │
          ├──► Dense Search (vector DB, filtered by intent)
          │
          ├──► Sparse Search (BM25, filtered by intent)
          │
          ▼
┌─────────────────────┐
│   Merge + Dedup     │   Combine dense + sparse candidates
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│   Cross-Encoder     │   Reranker re-scores each (query, chunk) pair
│   Reranker          │
└─────────┬───────────┘
          │
          ▼
      Top k results → Prompt
```

## Pipeline Stages

### 1. Chunking -- Three-Tier Strategy

**Problem**: Naive character splitting breaks mid-sentence. Pure semantic splitting struggles with mixed structured/unstructured documents (distinct short paragraphs vs. large blocks with internal headings).

**Solution**: A cascading approach that respects document structure first, then falls back to AI-based splitting.

| Tier | Method | When |
|------|--------|------|
| Paragraphs | Split on `\n\n` | Always (first pass) |
| Headings | Regex: short capitalized lines without end punctuation | When a paragraph exceeds `MAX_CHUNK_SIZE` |
| Semantic | LlamaIndex `SemanticSplitterNodeParser` | Last resort for large unstructured blocks |

**Why this order**: Paragraph boundaries are the strongest structural signal in text. Headings are the next most reliable. Semantic splitting (which groups sentences by embedding similarity) is powerful but can merge unrelated short paragraphs or split coherent narratives -- so it's used only when structure-based methods can't break a chunk down further.

**Why SemanticSplitterNodeParser over RecursiveCharacterTextSplitter**: `RecursiveCharacterTextSplitter` splits hierarchically by separators (`\n\n`, `\n`, ` `, `""`) but is purely character-count driven. It doesn't understand meaning. `SemanticSplitterNodeParser` computes embeddings for each sentence and groups them based on cosine similarity, producing chunks that are semantically coherent rather than just size-compliant.

### 2. Summary Chunks

**Problem**: Aggregation queries like "how many trips?" need a high-level overview, but vector search returns individual detail chunks.

**Solution**: Generate one summary chunk per file during ingestion. The summary lists section count and topic titles. Marked with `is_summary: True` metadata so the intent processor can prioritize them for aggregation queries.

### 3. Metadata

Every chunk carries:

| Field | Purpose |
|-------|---------|
| `source` | Original filename (e.g., `travel.md`) |
| `knowledge_type` | Filename without extension (e.g., `travel`, `cisco_work`) |
| `chunk_index` | Position within the file (-1 for summaries) |
| `is_summary` | Boolean flag for summary vs. detail chunks |

**Why**: Metadata enables filtered retrieval. When the intent processor detects the query is about Cisco, it filters to `knowledge_type=cisco_work`, eliminating noise from unrelated documents.

### 4. Vector Store Abstraction

**Problem**: Tight coupling to a single vector database makes experimentation expensive.

**Solution**: `DBHandler` abstract base class with concrete implementations for Qdrant and Chroma. Switching databases requires changing one `.env` variable.

```
DBHandler (ABC)
    ├── ChromaHandler    (langchain-chroma)
    └── QdrantHandler    (qdrant-client, direct API)
```

**Why Qdrant as default**: Both Qdrant and Chroma support local file-based persistence. Qdrant was chosen as the default for its richer filtering API (nested payload fields, typed conditions) and better scaling characteristics. The `QdrantHandler` uses `qdrant-client` directly (not the LangChain wrapper) for full control over point structure and metadata handling.

**Handler factory**: `handlers/__init__.py` uses lazy imports via a registry dict, so unused handlers don't load their dependencies.

### 5. Hybrid Retrieval (Dense + BM25)

**Problem**: Dense (embedding) search finds semantically similar chunks but can miss exact terms. A query for "McCall" might not retrieve the chunk containing that name if the embedding model doesn't know it.

**Solution**: Run both searches in parallel and merge results.

| Search | Strength | Weakness |
|--------|----------|----------|
| Dense (vector DB) | Understands meaning, paraphrases | Misses rare names, codes, dates |
| BM25 (keyword) | Exact term matching, scores by rarity | No semantic understanding |

BM25 runs in-memory via `rank_bm25`. The index is built during `load()` or `connect()` from all stored documents. Both searches respect intent filters.

**Why not a single hybrid index**: Keeping dense and sparse search separate and merging before reranking gives full control over each signal. The reranker handles the fusion -- it doesn't care where candidates came from.

### 6. Cross-Encoder Reranking

**Problem**: Bi-encoder embeddings (used for dense search) encode the query and document independently. This is fast but misses fine-grained interactions between query and document tokens.

**Solution**: After collecting candidates from dense + BM25, a cross-encoder model scores each `(query, chunk)` pair jointly. This is slower (processes each pair through the full model) but significantly more accurate.

- **Bi-encoder** (retrieval): `embed(query)` vs `embed(doc)` → cosine similarity. Fast, runs on thousands of docs.
- **Cross-encoder** (reranking): `model(query + doc)` → relevance score. Slow, runs on ~10-20 candidates.

The pipeline fetches `candidates` (default 10) from each search, merges them, and the reranker picks the best `k`.

### 7. Intent Processing (QueryProcessor)

**Problem**: Without query understanding, every query searches the entire corpus with the same strategy. "Give me Cisco struggles" wastes time scoring travel chunks.

**Solution**: A lightweight, no-LLM query analyzer with two-tier knowledge type detection and aggregation pattern matching.

**Knowledge type detection**:

| Tier | Method | Example |
|------|--------|---------|
| Keyword match | Check if knowledge type name parts appear in query | "cisco" in query → `cisco_work` (confidence 1.0) |
| Embedding similarity | Cosine similarity between query and type descriptions | "trips" ≈ "travel" (confidence 0.61) |

**Confidence gating**: The filter is only applied when:
- Confidence > 0.5 (below this, the match is too uncertain)
- Gap between top two scores > 0.05 (prevents filtering on ambiguous queries like "what did I do at work?" which could match both `cisco_work` and `aetna_work`)

**Aggregation detection**: Regex patterns for "how many", "how much", "count", "summarize", etc. When detected, summary chunks are retrieved first, then detail chunks fill remaining slots.

## Project Structure

```
rag/
├── .env                         # Model names, DB choice, chunking params
├── knowledge/                   # Source documents (drop .md/.txt files here)
│   ├── travel.md
│   ├── cisco_work.md
│   └── aetna_work.md
├── db/                          # Persisted vector store (auto-created)
└── core/
    ├── config.py                # Loads .env, provides typed config variables
    ├── main.py                  # Orchestration: ingest, chunk, query, prompt
    ├── store.py                 # VectorStore: hybrid retrieval, reranking, BM25
    ├── query.py                 # QueryProcessor: intent detection, routing
    └── handlers/
        ├── __init__.py          # Handler factory (lazy loading)
        ├── base.py              # DBHandler abstract base class
        ├── chroma.py            # Chroma implementation
        └── qdrant.py            # Qdrant implementation (default)
```

## Configuration

All settings are in `.env` -- no code changes needed to switch models or databases.

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | HuggingFace embedding model name |
| `RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Cross-encoder model for reranking |
| `VECTOR_DB` | `chroma` | Vector database backend (`chroma` or `qdrant`) |
| `SUPPORTED_EXTENSIONS` | `.md,.txt` | File types to ingest from knowledge folder |
| `MAX_CHUNK_SIZE` | `1000` | Max characters per chunk before splitting further |
| `BREAKPOINT_PERCENTILE` | `85` | Semantic splitter sensitivity (higher = fewer splits) |

Models are downloaded once from HuggingFace and cached locally at `~/.cache/huggingface/hub/`. After the first run, everything works offline.

## Running

```bash
cd rag/core
python main.py
```

This will:
1. Read all files from `knowledge/`
2. Chunk them using the three-tier strategy
3. Generate summary chunks per file
4. Load everything into the vector store (resets on each run)
5. Run test queries with intent analysis and hybrid retrieval

## Models Used

| Role | Model | Size | Why |
|------|-------|------|-----|
| Embedding | `BAAI/bge-large-en-v1.5` | ~1.3 GB | Strong general-purpose embeddings, top MTEB benchmark performer |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` | ~80 MB | Fast cross-encoder trained on MS MARCO passage ranking |
| Semantic chunking | Same as embedding model | -- | Reused for `SemanticSplitterNodeParser` sentence grouping |

All models are local and free. No API keys or cloud services required.

## Design Decisions

### Why no LLM in the retrieval loop?
The pipeline builds a prompt with retrieved context but does not call an LLM for generation. This is intentional -- it keeps the retrieval pipeline testable, fast, and independent of any LLM provider. The prompt output can be sent to any LLM (local or API) as a separate step.

### Why context managers for VectorStore?
Qdrant's local client holds file locks and background threads. Without explicit cleanup, Python's shutdown sequence can raise `ImportError: sys.meta_path is None`. The `with VectorStore() as store:` pattern guarantees `close()` runs even on exceptions.

### Why hash-based document IDs?
`hashlib.sha256(f"{filename}::{index}::{content}")` produces deterministic IDs. The same content always gets the same ID, enabling idempotent re-ingestion and duplicate detection.

### Why BM25 in-memory instead of a dedicated sparse index?
For the current corpus size (tens to hundreds of chunks), in-memory BM25 via `rank_bm25` is instantaneous and adds zero infrastructure. The index rebuilds in milliseconds during `load()` or `connect()`.

## Future Enhancements

### Multi-Query Retrieval
Generate multiple reformulations of a query and retrieve for each, then merge all candidates before reranking. Captures different angles of ambiguous queries.
- **Without LLM**: Template-based variants (keyword extraction, stop-word removal, reordering).
- **With LLM**: Ask a local model to generate 2-3 diverse rephrasings.
- **Tradeoff**: Each variant runs a full retrieval cycle, so 3 variants = ~3x latency.

### Contextual Compression
After retrieval, trim each chunk to only the sentences relevant to the query. Reduces noise in the prompt context window.
- **Approach**: Use the existing cross-encoder to score individual sentences within each retrieved chunk; keep only those above a threshold.
- **When it matters**: Becomes valuable with larger chunk sizes or less structured documents where chunks contain mixed topics.

### Richer Summary Chunks
Current summaries list first lines of sections. Improving them to produce structured overviews (e.g., "6 travel stories covering Munich, Caribbean, Australia...") would give better answers for aggregation queries.

### LLM Integration
Wire up a local LLM (Ollama, llama.cpp, or HuggingFace Transformers) to consume the prompt and generate final answers. The pipeline already produces the prompt -- this is the last mile.

### Incremental Ingestion
Current `load()` resets the store on each run. Adding incremental mode (hash-based change detection, upsert only new/modified chunks) would support growing knowledge bases without full re-indexing.

### Additional File Formats
Extend `extract_content_from_files` to handle PDFs (via `pymupdf` or `pdfplumber`), DOCX, HTML, and code files. Each format would need its own extraction logic but feeds into the same chunking pipeline.

### Evaluation Framework
Systematic retrieval quality measurement: build a test set of (query, expected_chunks) pairs and track precision/recall/MRR as you change models, chunking parameters, or retrieval strategies.


Sample prompts:
"give all struggling areas in work cisco",
"how many trips have I taken?",
"what happened in the Caribbean?",
"what did I do at Aetna?",



    # prompt = (
    #     "Answer only from the context below. If not found, say you don't know.\n\n"
    #     f"Context:\n{context}\n\n"
    #     f"Question: {query}"
    # )
    # response = Settings.llm.complete(prompt)
    # return response.text

## Observations:

**OBRV1:**
#### For data 1: user1:
Chunking began...
Generated 34 chunks.
Original Length: 7385 | Chunked Length: 7074
['The "Deep Space" Project Log (Stress Test)\ntext\nDOCUMENT: ALPHA-CENTAURI MISSION LOG v9.0\nClassification: TOP SECRET\nTags: Space, Propulsion, Urgent', '1. MISSION OBJECTIVE\nThe primary goal is the deployment of the "Chronos" Warp Engine. \nNote: "Gravity is not a limit, it\'s a suggestion." -- Dr. V (Lead Scientist)', '2. PROPULSION SYSTEM SPECS\nThe engine utilizes a tri-phase liquid cooling system.\n* Primary Cooling\n    - Liquid Nitrogen (Sub-zero)\n    - Helium-3 (Experimental)\n        * Warning: Highly Volatile\n        * Requires: Gold-plated shielding\n* Secondary Backup\n    - Standard Radiators', '3. ENGINE INITIALIZATION CODE\nIf the core temperature exceeds 4000K, execute this override:\n```bash\n# Emergency Shutdown Sequence\nstop --all-turbines\nflush --coolant-valves\necho "Manual Override Initiated by @EngineeringTeam"\nreturn 0\nUse code with caution.\n```', 'FUEL INVENTORY & CONSUMPTION\nBelow is the status of our current fuel reserves for the 2027 launch:\nFuel Type\tVolume (L)\tEfficiency\tRisk Level\nDark Matter\t500\t99.9%\tExtreme\nHydrogen\t25000\t12.5%\tLow', 'Anti-Matter\t50\t100%\tCritical\nEMERGENCY CONTACTS', 'Main Hangar: Sector 7-G\nMars Colony 1, Olympus Mons', 'Outer Rim Territories\nMAINTENANCE BACKLOG', 'Calibrate the thermal sensors for @DrV\nReplace the cracked viewing port on Deck 4.\nFinalize the AI "Aura" personality matrix.', 'CONCLUSION & NEXT STEPS\nFinal review is scheduled for Monday. Ensure all @Scientists have signed the waiver.', 'The "Chaos" Derived Text Example\nPROJECT "NEBULA" INTERNAL WIKI v2.1\nStatus: DRAFT [Internal Only]\nAuthor: @SystemAdmin', '1. EXECUTIVE OVERVIEW\nThis project aims to bridge the gap between our legacy COBOL systems and the new React-based frontend.\nNote: "If we fail to migrate the database by Q3, the entire stack becomes legacy."', '2. INFRASTRUCTURE & DEPLOYMENT\nWe are utilizing a hybrid-cloud approach. The primary regions are:\n* North America (Primary)\n    * us-east-1 (Virginia)\n    * us-west-2 (Oregon)\n* Europe (Failover)\n    * eu-central-1 (Frankfurt)', '3. CORE CONFIGURATION (DO NOT SHARE)\nTo initialize the environment, run the following snippet:\n```javascript\nconst init = async (key) => {\n  const connection = await DB.connect(key);\n  console.log("Connected to @DatabaseCluster");\n  return connection;\n};\n```', '1. SHIPPING LOGISTICS & PRICING\n   The following table outlines the current shipping tiers for 2026:\n| Region | Tier 1 | Tier 2 | Notes |\n|---|---|---|---|\n| USA | $5.00 | $12.00 | Standard |\n| EU | €4.50 | €11.00 | VAT Incl. |\n| ASIA | $8.00 | $20.00 | Express Only |', '1. CONTACT DIRECTORY\n   Main Office: 1234 Innovation Way\n   Silicon Valley, CA 94043\n   United States of America\n2. PENDING TASKS\n3. Complete the security audit for @SecurityTeam\n6. Rotate the production SSL certificates.', '7. MISCELLANEOUS NOTES\nQuarterly Engineering Roadmap: Phase 2 Strategy', 'Introduction and Core Mission\nThe primary objective for this quarter is to stabilize our cloud infrastructure and reduce technical debt across the legacy microservices. We aim to achieve 99.99% uptime by the end of Q4.', 'Key Performance Indicators (KPIs)\n* Infrastructure Cost: Reduce monthly spend by 15% through instance rightsizing.\n* Latency: Decrease P99 response times for the Auth API to under 200ms.\n* Developer Velocity: Increase the average number of PRs merged per week by 10%.', 'Proposed System Architecture\nThe migration from the monolith to a serverless architecture remains our top priority. By utilizing AWS Lambda and DynamoDB, we expect to see significant improvements in auto-scaling capabilities.', 'Critical Security Protocols\n1. Implement OAuth2 with OpenID Connect for all internal tools.\n2. Rotate all production secrets and transition to HashiCorp Vault.\n3. Conduct bi-weekly automated dependency vulnerability scans.', 'Budgetary Considerations\nThe total allocated budget for Phase 2 is $450,000. This covers third-party licensing, cloud credits, and the onboarding of two senior site reliability engineers.', '"True excellence in engineering is not about complex code, but about simple, maintainable solutions to complex problems." - Lead Architect', 'Next Steps\nWe will convene on Monday to assign specific owners to these workstreams. Please ensure your Jira boards are updated before the meeting starts.', 'EXECUTIVE SUMMARY: GLOBAL DIGITAL TRANSFORMATION 2026\nThis comprehensive report details the strategic shift toward integrated artificial intelligence and decentralized infrastructure across our enterprise divisions. As we move into the second half of the decade, the focus transitions from mere "digitization" to "autonomous optimization" of all core workflows.', '1. INFRASTRUCTURE MODERNIZATION AND EDGE COMPUTING\nThe migration to decentralized edge nodes has reduced latency by an average of 42% for our end-users in the APAC and EMEA regions. By moving computation closer to the data source, we have mitigated the risks associated with centralized cloud failures.', '* Deployment of 15,000 edge micro-servers.\n* Implementation of automated failover protocols.\n* Integration with regional green energy grids to reduce carbon footprint by 20%.', '1. AI-DRIVEN ANALYTICS AND PREDICTIVE MODELING\nOur data science team has successfully deployed the "NeuralNexus" model, which now handles real-time logistics forecasting. This shift allows for:\n1. Predictive maintenance on hardware before failure occurs.\n2. Dynamic pricing models based on hyper-local demand spikes.\n3. Automated customer sentiment analysis across 14 languages.', 'It is critical to note that all models are audited bi-monthly for algorithmic bias to ensure compliance with the new Global AI Ethics Framework (GAIEF).', '1. CYBERSECURITY AND ZERO-TRUST ARCHITECTURE\nWith the rise of quantum-resistant threats, we have transitioned our entire security stack to a Zero-Trust Architecture (ZTA). No device, whether internal or external, is trusted by default.\n"The perimeter is no longer a physical wall; it is a cryptographic identity." - Chief Security Officer.\nKey updates include:', '* Biometric multi-factor authentication (MFA) for all administrative access.\n* End-to-end encryption for metadata in transit.\n* Sandbox isolation for all third-party API integrations.', '1. FINANCIAL PROJECTIONS AND RESOURCE ALLOCATION [1, 2]\nThe board has approved an additional $1.2M for the "Project Phoenix" initiative. This capital is strictly earmarked for R&D in sustainable semiconductor materials.', 'We expect a ROI of 18% within the first three years of production. Current burn rates remain within acceptable margins, though we are monitoring the volatility of the rare-earth metal markets closely to prevent supply chain bottlenecks.\nAPPENDED SUPPLEMENTARY DATA: Ongoing monitoring of the aforementioned systems indicates that the transition phase is 85% complete.', 'We have observed a marked increase in employee productivity due to the reduction in manual data entry tasks. Future updates will focus on the "Quantum-Ready" encryption phase scheduled for Q1 2027. All stakeholders are advised to keep their local environments updated to the latest security patch (v4.5.1) to ensure compatibility with the new identity management gateway. [1]']
Data upserted successfully, total points: 34

Question: How to calibrate thremal sensors for deck4?
Calibrate the thermal sensors for @DrV
Replace the cracked viewing port on Deck 4.
Finalize the AI "Aura" personality matrix.

Anti-Matter     50      100%    Critical
EMERGENCY CONTACTS

Critical Security Protocols
1. Implement OAuth2 with OpenID Connect for all internal tools.
2. Rotate all production secrets and transition to HashiCorp Vault.
3. Conduct bi-weekly automated dependency vulnerability scans.

Introduction and Core Mission
The primary objective for this quarter is to stabilize our cloud infrastructure and reduce technical debt across the legacy microservices. We aim to achieve 99.99% uptime by the end of Q4.

3. CORE CONFIGURATION (DO NOT SHARE)
To initialize the environment, run the following snippet:
```javascript
const init = async (key) => {
  const connection = await DB.connect(key);
  console.log("Connected to @DatabaseCluster");
  return connection;
};
```
---- END ----

#### For data 2: user2:

