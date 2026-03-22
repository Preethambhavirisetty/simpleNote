### Run postgres with podman:
podman run -d \
  --name notelite-postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=notelite \
  -p 5432:5432 \
  docker.io/library/postgres:16

podman logs -f notelite-postgres

## Transitioned from simplenote to notelite
**Rename while container is running**
podman exec -it simple-note-postgres psql -U postgres -c "ALTER DATABASE simplenote RENAME TO notelite;"

**Rename the container:**
podman stop simple-note-postgres
podman rename simple-note-postgres notelite-postgres
podman start notelite-postgres

# container name
podman ps

# database name
podman exec -it notelite-postgres psql -U postgres -c "\l"

# Drop tables
podman exec -it notelite-postgres psql -U postgres -d notelite -c "
DROP TABLE IF EXISTS notetags CASCADE;
DROP TABLE IF EXISTS notes CASCADE;
" 2>&1

For prod:
- Set up Alembic — create_all won't handle future schema changes
  - pip install alembic
  - alembic init alembic
- Set secure=True on the cookie in token.py (currently False for local HTTP dev)

BE:
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements
uvicorn app.main:app --port 3001 --reload

Agent:
uvicorn main:app --port 3002
QUEUE service: docker run -d -p 6379:6379 redis
celery -A apis.worker:worker_app worker -l info -Q ingestion -P solo

FE:
npm i
npm run dev

Tests:
python -m pytest tests/ -v


```
project_root/
├── app/
│   ├── api/                # Route handlers (Interface layer)
│   │   └── v1/             # Versioned API endpoints
│   │       ├── api.py      # Main router that includes all sub-routers
│   │       └── endpoints/  # Specific routes (e.g., users.py, items.py)
│   ├── core/               # App-wide configurations
│   │   ├── config.py       # Pydantic BaseSettings for env vars
│   │   └── security.py     # JWT, hashing, and auth logic
│   ├── db/                 # Database connection and session management
│   │   ├── base.py         # Import all models here for Alembic
│   │   └── session.py      # SQLAlchemy/Tortoise engine & session local
│   ├── models/             # Database models (SQLAlchemy/Tortoise)
│   ├── schemas/            # Pydantic models for request/response validation
│   ├── services/           # Complex business logic (Service layer)
│   ├── crud/               # Reusable CRUD operations
│   └── main.py             # App entry point; initializes FastAPI()
├── tests/                  # Unit and integration tests
├── alembic/                # Database migrations
├── .env                    # Environment variables
├── docker-compose.yml      # Container orchestration
└── pyproject.toml          # Dependency management (Poetry/Pip)
```


### Endpoints:

- Auth: (`/api/auth`)
  - `POST   /register`          — Register a new user, sets HTTP-only cookie
  - `POST   /login`             — Login, sets HTTP-only cookie
  - `DELETE /logout`            — Logout, clears cookie · *requires auth*
  - `PATCH  /change-password`   — Change own password · *requires auth*
  - `POST   /forgot-password`   — Request a 6-digit OTP reset code (sent via email)
  - `POST   /reset-password`    — Reset password using OTP code · max 5 attempts · 15 min expiry

- User: (`/api/users`)
  - Own profile · *requires auth*
    - `GET    /me`              — Get own profile
    - `PATCH  /me`              — Update own name / email
    - `DELETE /me`              — Delete own account

  - Admin only · *requires `admin` role*
    - `GET    /`                — List all users · supports `?skip=&limit=`
    - `GET    /{user_id}`       — Get any user by id
    - `PATCH  /{user_id}`       — Update any user's name / email
    - `DELETE /{user_id}`       — Delete any user
    - `PATCH  /{user_id}/roles`       — Assign roles to a user
    - `PATCH  /{user_id}/activate`    — Activate a user account
    - `PATCH  /{user_id}/deactivate`  — Deactivate a user account

- Folder: (`/api/folders`) · *requires auth*
  - `GET    /`                        — List own folders · pinned first · supports `?skip=&limit=`
  - `POST   /`                        — Create folder · 409 if name already exists
  - `GET    /{folder_id}`             — Get folder by id
  - `PATCH  /{folder_id}`             — Update folder name / is_pinned · 409 if new name conflicts
  - `DELETE /{folder_id}`             — Delete folder · notes become unfiled (not deleted)

- Notes: (`/api/notes`) · *requires auth*
  - `GET    /`                        — List own notes · supports `?folder_id`, `?pinned_only`, `?search`, `?skip`, `?limit`
  - `POST   /`                        — Create note · content_text auto-extracted from TipTap JSON
  - `GET    /{note_id}`               — Get note with tags
  - `PATCH  /{note_id}`               — Update note · content_text auto-updated when content changes
  - `PATCH  /{note_id}/move`          — Move note to a folder or inbox (`folder_id: null`)
  - `DELETE /{note_id}`               — Delete note
  - `POST   /{note_id}/tags/{tag_id}` — Add tag to note · 409 if already tagged
  - `DELETE /{note_id}/tags/{tag_id}` — Remove tag from note

- Tags: (`/api/tags`) · *requires auth*
  - `GET    /`                        — List own tags · alphabetical
  - `POST   /`                        — Create tag · 409 if name already exists
  - `GET    /{tag_id}`                — Get tag by id
  - `PATCH  /{tag_id}`                — Rename tag · 409 if new name conflicts
  - `DELETE /{tag_id}`                — Delete tag · removed from all notes automatically


## Reference(docker, github actions)
### Files created

**`backend/Dockerfile`** — multi-stage, production-ready image

```
Stage 1 (builder): pip install --prefix=/deps → /deps
Stage 2 (runtime): python:3.12-slim, non-root "app" user, copies /deps → /usr/local
```

Key security properties from the workspace rules:
- Runs as a non-root user (`adduser --system app`)
- No secrets baked in — `POSTGRES_DB_URL`, `SECRET_KEY` must be injected at runtime
- `PYTHONDONTWRITEBYTECODE=1` and `PYTHONUNBUFFERED=1` set
- Health-check using stdlib `urllib` (no curl needed)
- `.dockerignore` excludes `.env`, `tests/`, `requirements-dev.txt`, `__pycache__`, etc.

**`backend/ruff.toml`** — linter config
- Checks E, F, W, I (errors, pyflakes, warnings, isort)
- Line length 120 (suitable for FastAPI)
- Per-file ignores: `F821` in models (SQLAlchemy string forward-refs), `F401` in `session.py` (side-effect import)

**`.github/workflows/ci.yml`** — 4-job pipeline

| Job | When | What |
|---|---|---|
| `lint` | every PR / push | `ruff check app/ tests/` |
| `test` | every PR / push | `pytest tests/ -v --strict-markers` |
| `docker-build` | after `test` passes | builds image, does **not** push |
| `docker-push` | push to `main` only | builds + pushes to `ghcr.io` with `sha-*` and `latest` tags |

### Enforcing merge protection in GitHub

To block merges when tests fail, go to **Settings → Branches → Add rule** for `main`:

1. Enable **"Require status checks to pass before merging"**
2. Add `Tests (pytest)` as a required check
3. Optionally add `Lint (ruff)` too
4. Enable **"Require branches to be up to date before merging"**


### Vector DB support
You’re already 80% there — you just need to add embeddings + indexing on top of your existing table.

Let’s walk through a **practical FastAPI + PostgreSQL setup** using **pgvector**.

---

# 1. Update your PostgreSQL schema

First, enable pgvector:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Now modify your table:

```sql
ALTER TABLE etl_data
ADD COLUMN embedding vector(1536);  -- 1536 for OpenAI embeddings
```

> 1536 is the dimension used by many models from OpenAI (e.g. text-embedding models)

---

# 2. Generate embeddings in FastAPI

Install dependencies:

```bash
pip install openai psycopg2-binary sqlalchemy
```

Example embedding function:

```python
from openai import OpenAI

client = OpenAI()

def get_embedding(text: str):
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return response.data[0].embedding
```

---

# 3. Store embeddings when inserting data

Your FastAPI model might look like:

```python
from sqlalchemy import Column, Integer, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class ETLData(Base):
    __tablename__ = "etl_data"

    id = Column(Integer, primary_key=True)
    text = Column(Text)
    embedding = Column(ARRAY(float))  # or use pgvector type
```

Insert with embedding:

```python
def insert_data(session, text):
    embedding = get_embedding(text)

    row = ETLData(
        text=text,
        embedding=embedding
    )
    session.add(row)
    session.commit()
```

---

# 4. Create a vector index (IMPORTANT)

This makes similarity search fast:

```sql
CREATE INDEX ON etl_data
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

---

# 5. Query similar text (vector search)

Raw SQL example:

```sql
SELECT id, text
FROM etl_data
ORDER BY embedding <-> '[0.1, 0.2, ...]'
LIMIT 5;
```

In Python:

```python
def search_similar(session, query_text):
    query_embedding = get_embedding(query_text)

    results = session.execute("""
        SELECT id, text
        FROM etl_data
        ORDER BY embedding <-> :embedding
        LIMIT 5
    """, {"embedding": query_embedding})

    return results.fetchall()
```

---

# 6. Expose via FastAPI endpoint

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/search")
def search(q: str):
    results = search_similar(session, q)
    return [{"id": r[0], "text": r[1]} for r in results]
```

---

# Key ideas (what’s actually happening)

* Your `text` → converted into **vector embedding**
* Stored in PostgreSQL
* Queries also converted into embeddings
* Database finds **closest vectors (semantic similarity)**

---

# Common upgrades (next steps)

Once this works, you can improve it:

* Chunk long text before embedding
* Add metadata filters (`WHERE source = 'x'`)
* Use hybrid search (text + vector)
* Cache embeddings to reduce API cost
* Try HNSW index (better than IVFFlat in newer pgvector)

---

# TL;DR

You turned this:

```
text → stored in DB
```

into:

```
text → embedding → stored → similarity search
```


### Options
You’re thinking about exactly the right problem: **future portability**. The short answer is:

> Yes — embeddings are portable, databases are not.

So your strategy should be: **decouple embedding generation from storage**.

---

# Core idea

Whether you use:

* pgvector (inside PostgreSQL)
* or Qdrant

👉 the **embedding vectors themselves stay the same**

---

# Scenario 1: Start with PostgreSQL → move to Qdrant later

This is totally fine. Here’s what happens:

### What you already have

* `text`
* `embedding` (e.g. `[0.123, 0.456, ...]`)

### Migration process

You simply:

1. Export data from PostgreSQL
2. Insert into Qdrant

Example:

```python
points = [
    {
        "id": row.id,
        "vector": row.embedding,
        "payload": {"text": row.text}
    }
    for row in pg_rows
]

qdrant.upsert(collection_name="etl_data", points=points)
```

👉 No need to recompute embeddings (unless you change models)

---

# Scenario 2: Start directly with Qdrant

Then yes — you skip pgvector entirely:

```python
embedding = get_embedding(text)

qdrant.upsert(
    collection_name="etl_data",
    points=[{
        "id": id,
        "vector": embedding,
        "payload": {"text": text}
    }]
)
```

---

# The real architectural decision

The key is **don’t tie your app to the database**.

Instead of this:

```python
# BAD (tight coupling)
def search():
    return pgvector_query(...)
```

Do this:

```python
# GOOD (abstraction layer)
class VectorStore:
    def search(self, query: str):
        pass
```

Then implement:

```python
class PGVectorStore(VectorStore): ...
class QdrantStore(VectorStore): ...
```

👉 Now switching DB = swapping implementation

---

# Important gotchas (people miss these)

## 1. Embedding model lock-in

If you switch models from OpenAI (or others):

* Old embeddings ≠ new embeddings
* You MUST recompute everything

This is the **real migration cost**, not the DB.

---

## 2. Index differences

* pgvector → IVFFlat / HNSW (basic)
* Qdrant → optimized ANN, filtering, sharding

👉 After migration, you’ll need to **rebuild indexes**, but not vectors

---

## 3. Hybrid queries

PostgreSQL advantage:

```sql
WHERE category = 'finance'
ORDER BY embedding <-> query
```

Qdrant:

* Uses payload filters instead
* Slightly different query style

---

# Practical recommendation (what I’d actually do)

### If you're early stage / MVP:

Start with:

* PostgreSQL + pgvector

Why:

* Simpler infra
* One database
* Easier debugging

---

### If you expect scale / heavy search:

Start with:

* Qdrant

Why:

* Better performance
* Built for vector workloads

---

# Best practice (this is the key takeaway)

Store **both**:

* Raw text
* Embedding vector

AND optionally:

* Original source / metadata

This gives you:

* Easy migration
* Ability to re-index anywhere
* Flexibility to switch tools

---

# Clean mental model

Think of it like this:

```text
[text] --(embedding model)--> [vector] --(database)--> search
```

* Left side = AI model (hard to change)
* Right side = database (easy to change)

---

If you want, I can show:

* A **clean interface design** for swapping pgvector ↔ Qdrant
* Or a **real migration script** from PostgreSQL → Qdrant with batching and retries


write:
  - work
    - learnings
      - text
        - subtext1 json -> save
          - extract text from json => content(derived text) - CLEAR
          - if len(content) < 500: no chunking - CLEAR
          - else:
              - create semantic chunks + embed each chunk - CLEAR
                <!-- - generate short summary for each chunk - UNCLEAR
                - aggregate all summaries - UNCLEAR
                - embed consolidated summary - UNCLEAR -->
              - batch upsert all embedded chunks + embeded summary to vector DB - CLEAR
          - write subtext1 json & derived text - CLEAR
        - subtext1 + subtext2
        - subtext1 + subtext2 + subtext3
        ...

chat:
  - user prompt like "when did i go to trip last time?"
  - embed the query - CLEAR
  <!-- - get metadata -> how? - LATER
  - get user intent -> how? - LATER
  - generate confidence score for user's query; - LATER -->
  - query vector DB with filters(userid) - CLEAR
  - 

  <!-- - [edgecase] if low score like between 1 - 10%, then vague fallback to "could you elaborate on what you are referring to?" then give clarifying questions
  - [edgecase] if confidence score is still low but > 10%, then query vector DB over all the available notes, get top k, then summarize and give response -->

