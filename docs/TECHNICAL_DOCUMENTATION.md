# Notelite Technical Documentation

## Overview

**Notelite** is a full-stack note-taking application with AI-powered search, retrieval, summarization, and chat over a user's notes.

At a high level, the system is split into three main parts:

- **Frontend app** for the user interface.
- **Backend API** for authentication, notes, folders, tags, conversations, and user data.
- **Agent service** for AI ingestion, vector search, retrieval-augmented generation, streaming chat, and agent workflows.

The application is designed as a practical personal knowledge system: users write and organize notes, the backend stores the core records, and the agent service transforms note content into searchable AI artifacts.

## High-Level Architecture

**Notelite uses a service-oriented architecture.**

Instead of placing everything inside one large application, responsibilities are separated across focused services:

- **Frontend** handles the browser experience.
- **Backend** handles product data, authentication, and normal API operations.
- **Agent** handles AI-heavy work such as chunking, embeddings, summarization, retrieval, and chat.
- **Celery workers** handle slow background jobs without blocking user-facing requests.
- **PostgreSQL** stores relational application data and retrieval metadata.
- **Qdrant** stores vector embeddings for semantic search.
- **Redis** acts as the message broker and result backend for background tasks.
- **Prometheus, Loki, and Grafana** provide metrics, logs, and dashboards.

This structure keeps the core app responsive while allowing AI processing to run asynchronously and independently.

## Frontend Stack

The frontend is built with **React** and **Vite**.

**Main frontend technologies:**

- **React 19** for building interactive UI components.
- **Vite** for fast local development and optimized frontend builds.
- **React Router** for page routing.
- **Zustand** for lightweight client-side state management.
- **Axios** for API communication.
- **Tailwind CSS** for utility-first styling.
- **TipTap** for rich-text note editing.
- **React Markdown** and **remark-gfm** for rendering Markdown-style chat content.
- **Lucide React** for icons.

The frontend includes pages for home, login, registration, notes, folders, and chat. Protected routes are used so authenticated pages are only available to signed-in users.

## Backend Stack

The backend is built with **FastAPI**.

**Main backend technologies:**

- **FastAPI** for REST API endpoints.
- **Pydantic** for request and response validation.
- **SQLAlchemy** for database models and database access.
- **psycopg** for PostgreSQL connectivity.
- **Alembic** for database migrations.
- **PyJWT** for token-based authentication.
- **bcrypt** for password hashing.
- **Celery** for background task integration.
- **Redis** as the Celery broker and result backend.
- **httpx** for internal HTTP communication with the agent service.
- **structlog** and **python-json-logger** for structured logging.
- **Prometheus client** for application metrics.
- **boto3** for cloud/storage integration support.

The backend owns the main product entities: users, notes, folders, tags, conversations, and conversation messages.

## Agent Service Stack

The agent service is also built with **FastAPI**, but it has a different responsibility from the backend.

It focuses on AI workflows, note ingestion, embeddings, vector storage, retrieval, and chat streaming.

**Main agent technologies:**

- **FastAPI** for AI-related API endpoints.
- **Celery** for asynchronous ingestion and conversation work.
- **Qdrant client** for vector database operations.
- **LlamaIndex** for document and embedding abstractions.
- **LangGraph** for multi-step agent workflow orchestration.
- **tiktoken** for token counting and budget decisions.
- **spaCy** for named entity recognition.
- **dateparser** for extracting time-based signals from user queries and notes.
- **PyYAML** and **Jinja2** for prompt and configuration management.
- **httpx** for calling remote LLM and embedding services.
- **Prometheus client** for metrics.
- **structlog** for structured logs.

The AI models are designed to run remotely, such as on a GPU machine or hosted inference container, while the agent service can run on CPU infrastructure.

## Storage Architecture

Notelite uses two main storage systems because normal application data and AI retrieval data have different needs.

## PostgreSQL

**PostgreSQL stores structured application data.**

It is used for:

- Users.
- Notes.
- Folders.
- Tags.
- Conversations.
- Authentication-related records.
- Retrieval artifacts and document metadata.
- Version checks that prevent stale ingestion jobs from overwriting newer note data.

PostgreSQL is a good fit for this because the data is relational, transactional, and needs clear ownership rules.

## Qdrant

**Qdrant stores vector search data.**

It is used for:

- Chunk embeddings.
- Summary embeddings.
- Question embeddings.
- Dense vector search.
- Sparse vector search.
- Metadata-filtered retrieval by user, note, folder, or document.

The system separates chunk-level and summary-level retrieval so it can search both detailed passages and higher-level note summaries.

## Redis

**Redis is used as infrastructure for background work.**

It acts as:

- The Celery message broker.
- The Celery result backend.
- A queueing layer between API requests and long-running processing jobs.

This allows the backend and agent API to respond quickly while workers process heavy jobs in the background.

## Ingestion Architecture

The ingestion pipeline turns a normal note into AI-searchable material.

When a note is created or updated, the agent receives an ingestion request. The request can run directly for debugging, but the normal path is asynchronous through Celery.

**The ingestion flow is:**

1. Validate the request.
2. Check whether the job is stale compared with the latest note version.
3. Normalize and chunk the note text.
4. Extract keywords and entities.
5. Build chunk artifacts.
6. Embed and store chunk vectors in Qdrant.
7. Summarize the document.
8. Generate retrieval-focused questions.
9. Build summary and question artifacts.
10. Store summary and question vectors.
11. Store retrieval metadata in PostgreSQL.
12. Return stage timings, events, and processing results.

This design makes ingestion traceable, retryable, and easier to debug.

## Chunking Techniques

The agent uses a multi-stage chunking strategy instead of simply splitting text by character count.

**Chunking techniques include:**

- **Paragraph splitting** to respect natural writing boundaries.
- **Heading-aware splitting** to preserve document structure.
- **Semantic chunking** to group related sentences together.
- **Token-budget fallback chunking** to guarantee chunks stay within size limits.
- **Post-processing cleanup** for headings, lists, and formatting edge cases.

This helps produce chunks that are useful for retrieval and not just mechanically sliced text.

## Keyword And Entity Extraction

The ingestion pipeline extracts useful terms from note content.

It uses:

- **spaCy named entity recognition** to detect people, places, organizations, dates, and other entities.
- **Keyword extraction logic** to identify important concepts.
- **LLM-assisted deduplication** to clean up noisy or repeated keywords and entities.

The goal is to make retrieval richer than pure vector search alone. Keywords and entities provide extra signals for ranking, filtering, and explanation.

## Summarization Technique

The agent uses summarization to create note-level understanding.

For smaller notes, the system can summarize directly. For larger notes, it uses a hierarchical approach:

- Summarize groups of chunks.
- Merge those summaries.
- Produce a final document summary.

This avoids sending overly large note content to the model in one request and keeps summarization within token limits.

## Question Generation

After summarization, the system generates retrieval-focused questions.

These questions represent likely things a user might ask about the note. They are embedded and stored separately, which helps the retrieval system match natural user questions even when the exact wording does not appear in the original note.

## Retrieval And RAG Architecture

The chat system is built around **retrieval-augmented generation**, commonly called **RAG**.

In simple terms, RAG means the assistant does not answer from the language model alone. It first searches the user's notes, builds a relevant context, and then asks the model to answer using that context.

**The retrieval flow includes:**

- Query cleanup and normalization.
- Optional conversation-aware query contextualization for short follow-up questions.
- Time-signal detection for date-aware retrieval.
- Optional HyDE generation, where the model creates a hypothetical answer-like passage to improve search.
- Dense vector search for semantic similarity.
- Sparse vector search for keyword-style matching.
- Summary search to identify relevant documents.
- Question-vector search to match user questions to generated note questions.
- Chunk search for detailed evidence.
- Reciprocal rank fusion to combine multiple search result lists.
- Reranking to improve final result quality.
- Context assembly with token budgets.
- Citation/reference building for source visibility.

This gives the chat system multiple ways to find useful evidence instead of relying on one search method.

## Chat Streaming Architecture

The chat feature uses **server-sent events** for streaming.

The browser sends a chat request to the backend. The backend authenticates the user, attaches trusted user information, forwards the request to the agent, and streams the agent response back to the browser.

This gives users a live response experience while keeping the agent service private behind the backend.

## Agent Workflow Architecture

The project also includes a **LangGraph-based agent workflow**.

This workflow is organized into stages:

- **Planner** decides what needs to be done.
- **Executor** performs the selected actions and tool calls.
- **Approval** handles sensitive or destructive actions.
- **Reviewer** checks whether the result should be accepted or revised.

The graph can checkpoint state, resume paused work, stream events, and use a fast path for simple requests that do not need full tool-based reasoning.

This architecture is useful for more complex AI workflows where a single model call is not enough.

## API Design

The APIs follow a clean layered pattern.

**Backend API responsibilities:**

- Authentication.
- User profiles.
- Notes.
- Folders.
- Tags.
- Conversations.
- Feature flags.
- Chat proxying to the agent.

**Agent API responsibilities:**

- Ingestion.
- Ingestion status.
- Direct debugging ingestion.
- Chat completions.
- Streaming RAG chat.
- Prompt and shared diagnostic routes.

Responses generally use a consistent envelope with success or failure information, which makes frontend handling simpler.

## Authentication And Security

The system uses several security techniques.

**User authentication:**

- Passwords are hashed with bcrypt.
- JWT-based authentication is used for user sessions.
- Protected backend routes require a valid authenticated user.

**Internal service security:**

- Backend-to-agent communication uses an internal API key.
- Trace IDs from outside callers are not blindly trusted.
- Internal user headers are only trusted when paired with a valid internal key.

**Cookie and deployment security:**

- The containerized stack is configured to use secure cookies over HTTPS.
- Nginx serves the frontend and terminates public web traffic.
- Internal services communicate over the private compose network.

## Observability

The project includes an observability stack.

**Logging:**

- Structured logs are emitted by backend and agent services.
- Logs include trace IDs for request correlation.
- Loki is used for centralized log storage.

**Metrics:**

- Backend and agent expose Prometheus metrics.
- Request count and latency are tracked.
- Route labels use matched route templates to avoid high-cardinality metrics.

**Dashboards:**

- Grafana dashboards are provisioned for logs and pipeline metrics.
- Prometheus is configured for scraping metrics.

**Traceability:**

- Each request receives an `X-Trace-Id`.
- Ingestion returns a human-readable event list.
- Pipeline stages record timing information in milliseconds.

This makes debugging much easier because a single user action can be followed through logs, metrics, and ingestion events.

## Feature Flags

The application uses feature flags to control behavior.

Feature flags are loaded from a shared JSON file and used by both backend and frontend-facing flows.

This allows features such as chat to be enabled, disabled, or rolled out without deeply changing the application structure.

## Background Processing

Long-running tasks are handled with Celery workers.

This is especially important for ingestion because embedding, summarization, keyword extraction, and vector indexing can take multiple seconds.

Using a queue provides several benefits:

- User-facing requests return quickly.
- Slow AI jobs do not block API workers.
- Failed jobs can be inspected through task status.
- Work can be scaled by adding more workers.
- Separate queues can be used for ingestion and conversation work.

## Deployment Architecture

The project is containerized with Podman-compatible compose files.

The full stack includes:

- Frontend container served by Nginx.
- Backend FastAPI container.
- Agent FastAPI container.
- Agent Celery worker container.
- PostgreSQL container.
- Redis container.
- Qdrant container.
- Loki container.
- Grafana container.
- Prometheus container.

Persistent volumes are used for database data, vector storage, model caches, logs, dashboards, and metrics storage.

The frontend can also be run locally with Vite during development for a faster hot-reload experience.

## Testing And Quality Tools

The project includes automated tests for both backend and agent behavior.

**Backend tests cover:**

- Authentication.
- Users.
- Notes.
- Folders.
- Tags.
- Health checks.
- Migrations.
- TipTap content handling.
- Trace propagation.

**Agent tests cover:**

- Chunking behavior.
- Keyword and entity extraction.
- Summary processing.
- Retrieval pipeline behavior.
- HyDE behavior.
- Reranking.
- Shared HTTP error handling.
- Ingestion version guarding.
- Agent workflow behavior.
- Destructive action gating.

**Quality tools include:**

- pytest for Python tests.
- Ruff configuration for backend linting.
- ESLint for frontend linting.
- Alembic for controlled database schema changes.

## Optimizations Applied

Several optimizations are already present in the system.

## Asynchronous Ingestion

Ingestion runs through Celery so expensive AI work does not block normal API requests.

## Batched Embeddings

Embedding requests are batched where possible. This reduces network overhead and avoids making one remote call per sentence or chunk.

## Hybrid Search

Retrieval combines dense semantic vectors with sparse keyword-style vectors. This improves search quality because semantic similarity and exact-term matching catch different kinds of relevance.

## Summary-Level Search

The system searches note summaries before or alongside chunks. This helps identify relevant notes even when an individual chunk does not immediately rank highly.

## Question Vectors

Generated questions are indexed separately. This improves matching between natural user questions and note content.

## Reciprocal Rank Fusion

Multiple retrieval result lists are merged using weighted reciprocal rank fusion. This allows results from dense search, sparse search, summary search, question search, and filtered chunk search to contribute to a final ranking.

## Reranking

After initial retrieval, candidate results can be reranked to improve the final context that is sent to the language model.

## Token Budgets

The system uses token counting to keep chunks, summaries, history, and final context within practical model limits.

## Stale Version Guarding

Ingestion checks note versions before writing results. This prevents an older background job from overwriting a newer note update.

## Payload Indexes

Qdrant payload indexes are created for frequently filtered fields. This makes metadata-filtered vector search more efficient.

## Bounded Metrics Cardinality

Metrics use route templates rather than raw URLs. This prevents metrics storage from exploding with one label per unique request path.

## Controlled Threadpool Usage

The agent configures sync worker limits so streaming and synchronous routes do not accidentally consume unbounded threadpool capacity.

## Trace ID Propagation

Trace IDs are passed between trusted backend and agent calls. This makes cross-service debugging much easier.

## Error Handling And Resilience

The project applies several resilience techniques:

- Standardized API success and failure envelopes.
- Custom exception handlers.
- Retry-aware transient HTTP error classification.
- Graceful handling of remote inference failures.
- Health endpoints for services.
- Startup validation for Qdrant collection dimensions.
- Background job status endpoints.
- Delete-and-replace vector indexing to avoid stale orphaned chunks.

The system also records human-readable ingestion events so developers can understand what happened without reading raw logs first.

## Notable Design Choices

**The backend and agent are separate services.**

This keeps normal app behavior independent from heavier AI workflows.

**PostgreSQL and Qdrant are both used.**

PostgreSQL is best for relational product data. Qdrant is best for vector search. Keeping both allows each database to do what it is good at.

**The agent indexes chunks, summaries, and questions.**

This gives retrieval several levels of understanding: detailed passages, whole-note summaries, and natural question matching.

**The frontend uses Zustand instead of a heavier state framework.**

This keeps state management simple while still supporting notes, auth, folders, tags, settings, feature flags, and chat.

**Observability is treated as part of the application.**

Logs, metrics, dashboards, timings, and trace IDs are built into the stack instead of being added later.

## Current System Capabilities

The current project supports:

- User registration and login.
- Authenticated note management.
- Folder and tag organization.
- Rich-text editing with TipTap.
- Conversation storage.
- Feature-gated chat UI.
- Streaming chat responses.
- AI ingestion of notes.
- Semantic and hybrid vector retrieval.
- Summary and question generation.
- Background processing.
- Metrics and centralized logging.
- Containerized deployment.

## In Simple Terms

Notelite is more than a notes app. It is a notes app plus an AI retrieval engine.

The frontend gives users a clean place to write and chat. The backend protects and stores user data. The agent reads notes, breaks them into meaningful pieces, summarizes them, extracts useful concepts, stores searchable vectors, and uses those vectors to answer questions with context from the user's own notes.

The architecture is designed to be modular, observable, and scalable enough for AI-heavy workflows while still staying understandable as a product codebase.
