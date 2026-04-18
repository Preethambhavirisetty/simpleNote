Existing pipeline stages(04/16/2026)
1. ingestion
    1. chunking: structural + semantic
    2. keywords + entities extraction
    3. keywords dedup(llm)
    4. recursive summarization(llm)
    5. question generation(llm)
    6. llama document assembly
2. chat stream
    0. llm call(standalone)
    1. query rewriting(standalone)
    2. rag retrival
        1. summary search(cosine)
        2. doc scoping
        3. chunk search(cosine)
        4. soft scoring
        5. reranking(model)
    3. intent + strategy
    4. context assembly
    5. build prompt
    6. inference(llm)
    7. stream(sse)


### intent classification
intents / converage of user goals
- understand / recall - semantic
- intent=locate / find
    - which note has ...? / where did I put the API key section? / Find my recepe for z
    - if need a structured "note title + snippet"
    - include folder name + note title + snippet
    - semantic intent still covers but need to include folder id and note id details in every prompt(citations) 
- enumerate / inventory
    - list all notes about travel / everything tagged work / notes in folder
    - distinguis scoped list vs vague
    - deterministic + short answers
- count / quantify
    - how many times did I mention x / how many notes talk about debt
    - keyword_count / phrase occurences vs note count
- time
    - when did I write this / what did I add last week / notes from march
    - via metadata: filters, sorts, lists
    - extract dates from text vs semantic
- yes / no / presence
    - did I ever note down x / do i have something on y
    - semantic + boolean path with explicit yes/no + sources
- compare synthesize across notes
    - compare a and b / contradictions between 2 write ups
    - compare only as a prompt template
- "category": "Tasks / Todos",
    - "intent": "todo_management",
    - "description": "Manage or query tasks and to-do items within notes.",
    - "goal": "Reserved for future enhancement to integrate explicit task extraction and management."
- meta about the corpus
    - how many notes do i have / largest note / empty folders
    - corpus_stats
- conversation / UI meta
    - what did I ask you before / repeat last answer
    - separate handling so "note intents" don't get polluted
    - conversation support + route users to this intent when needed
- unsafe / ambigous
    - missing topic / contradictory request / needs disambuation
    - clarify intent (as one question) stable than adding 5 new content intents

User Query
    │
    ▼
┌───────────────────────────────┐
│  Layer 0: Quick Rules         │  (regex for obvious cases)
│  "how many notes do I have"   │  → corpus_stats (skip everything)
│  "repeat that"                │  → conversation_meta
│  Cost: 0, Latency: <5ms      │
└──────────────┬────────────────┘
               │ no match
               ▼
┌───────────────────────────────┐
│  Layer 1: Vector DB Lookup    │
│  Top 1 per intent → best 3   │
│  Evaluate agreement + scores  │
└──────────────┬────────────────┘
               │
       ┌───────┴────────┐
       │                 │
   High confidence    Low confidence
   (agree + >0.78)   (disagree or <0.72)
       │                 │
       ▼                 ▼
  Return intent    ┌─────────────────┐
  directly         │  Layer 2: LLM   │
  (no LLM call)    │  with exemplars  │
                   │  as few-shot     │
                   └────────┬────────┘
                            │
                    ┌───────┴────────┐
                    │                 │
                Confident        Still unsure
                (>0.60)          (<0.60)
                    │                 │
                    ▼                 ▼
              Return intent    clarify_intent
                              (ask user)


### Run postgres with podman:
podman run -d \
  --name notelite-postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=notelite \
  -p 5432:5432 \
  docker.io/library/postgres:16

podman logs -f notelite-postgres

### Ignores saved creds
git -c credential.helper= push origin notelite-v2-enhancement

### to check local settings
git config --local -l


**Secure ingestion queue pipeline**
python3 -c "import secrets; print(secrets.token_hex(32))"
podman exec -it myredis redis-cli CONFIG SET requirepass "433452754217808211124" -> OK

**Set this later on cloud instance**
bind 127.0.0.1 -::1
requirepass <your-password>

## Transitioned from simplenote to notelite
**Rename while container is running**
podman exec -it notelite-postgres psql -U postgres -d notelite -c "ALTER DATABASE simplenote RENAME TO notelite;"
podman exec -it notelite-postgres psql -U postgres -d notelite -c "SELECT * FROM users;"

**Rename the container:**
podman stop notelite-postgres
podman rename simple-note-postgres notelite-postgres
podman start notelite-postgres

# container name
podman ps

# database name
podman exec -it notelite-postgres psql -U postgres -c "\l"
podman exec -it mypostgres psql -U postgres -c "\l+" -> gives the size of db


### PODMAN COMMANDS
podman system prune -a --volumes
podman-compose up -d --build

podman-compose build --no-cache backend
podman-compose up -d --force-recreate backend backend-celery
podman-compose build agent
podman rm -f notelite-agent notelite-agent-celery
podman-compose up -d agent agent-celery
podman logs --tail 20 notelite-backend-celery
### Verify all 8 containers are up
podman ps --format "table {{.Names}}\t{{.Status}}"

# Fix backend-celery (separate image from backend)
podman-compose build --no-cache backend-celery
podman rm -f notelite-backend-celery
podman-compose up -d backend-celery

# Fix inference (static build, no .so needed)
podman rm -f notelite-inference
podman-compose build inference
podman-compose up -d inference

```bash
podman ps -a --filter name=notelite-inference --format "table {{.Names}}\t{{.Status}}"
podman ps -a --filter name=notelite-inference

cd /Users/rbhaviri/Desktop/_others/simpleNote/v2
podman-compose up -d redis postgres qdrant


podman stop myredis mypostgres nl-qdrant
podman stop notelite-backend notelite-backend-celery notelite-agent notelite-agent-celery

podman rm -f notelite-backend notelite-backend-celery notelite-agent notelite-agent-celery
podman-compose build --no-cache backend backend-celery agent agent-celery
podman-compose up -d backend backend-celery agent agent-celery


podman-compose build --no-cache backend backend-celery
podman-compose build --no-cache agent
podman-compose build inference        # static build, skips cached broken layers


podman rm -f notelite-backend notelite-backend-celery notelite-agent notelite-agent-celery
podman-compose up -d agent agent-celery


> podman ps --format "table {{.Names}}\t{{.Status}}"

NAMES                    STATUS
myredis                  Up 12 minutes
mypostgres               Up 11 minutes
nl-qdrant                Up 11 minutes
notelite-inference       Up 11 minutes
notelite-backend         Up 11 minutes
notelite-backend-celery  Up 11 minutes
notelite-agent           Up 10 seconds
notelite-agent-celery    Up 10 seconds
```
Lightweight solutions for keyword extraction
pip install yake spacy
python -m spacy download en_core_web_sm
- yake -> high priority
- spacy(noisy + broad) -> phrases -> needs filtering to remove junk with the help of a custom helper function
- combine results with not just dedup but with semantic dedup and dominance pruning
- sort and return top 12 results

eg., semantic deduping(kw in existing and existing in kw)
input: ["winston", "inspector winston", "late", "summer", "late summer"]
output: ["inspector winston", "late summer"]


is it too complicated? why couldn't you implement chat and stream feature properly? its pretty straightforward right? new chat -> ask questions get responses -> saves it in the BG to DB -> reload get all conversations for the user for the chat, when clicked on a chat, put it in the route and API call to convverations/{chatid} and render all chats




### STARTUP STEPS
- podman machine start
- cd simpleNote/v2
- podman-compose up -d
- podman ps
- npm run dev
- cd notelite_inference && ./build/inference_api
- podman logs -f --tail 20 notelite-backend -> note apis
- podman logs -f --tail 20 notelite-agent-celery -> ingestion


## Notelite Inference:
> sysctl hw.memsize 2>/dev/null; sysctl machdep.cpu.brand_string 2>/dev/null     # to know hw related information, like memory size or cpu brand
hw.memsize: 19327352832
machdep.cpu.brand_string: Apple M3 Pro

> configure n_ctx and n_gpu layers via LLAMA_N_CTX and LLAMA_N_GPU_LAYERS env vars
> **Apple Silicon uses unified memory where CPU and GPU share the same RAM, and llama.cpp uses Metal to accelerate inference on it. That's your GPU.**

### quick stats
Workload	Typical input	Typical output	Fits in 8k?
Summarization (chunking_service)	~500-1500 tokens	~50-200 tokens	Easily
Query parsing / intent	~50-200 tokens	~10-50 tokens	Easily
Question generation	~500-1500 tokens	~50-100 tokens	Easily
Chat Q&A (single turn)	~200-500 tokens	~100-500 tokens	Easily
Chat Q&A (12 turns history)	~2000-4000 tokens	~500 tokens	Yes

### PLAN FOR CUTTING ON CONTEXT SIZE:
Total budget:     8192 tokens (or whatever n_ctx is)
─ System prompt:  ~200 tokens (fixed)
─ User query:     ~50-200 tokens (varies)
─ Response room:  ~1024 tokens (reserve for model output)
─ Template overhead: ~50 tokens (chat template markers)
────────────────────────────────
= Context budget:  ~6700-6900 tokens available for Qdrant chunks
Then when filling from Qdrant results (already ranked by relevance):

Iterate chunks in relevance order
Estimate each chunk's token count (rough: len(text) / 4 for English, or use a proper tokenizer)
Accumulate until the budget is exhausted
Drop remaining lower-ranked chunks entirely -- don't truncate a chunk mid-sentence


BUGS:
1.
1.1.3 wcwidth-0.6.0 weasel-1.0.0 wrapt-2.1.2 yake-0.7.3 yarl-1.23.0
WARNING: Running pip as the 'root' user can result in broken permissions and conflicting behaviour with the system package manager, possibly rendering your system unusable. It is recommended to use a virtual environment instead: https://pip.pypa.io/warnings/venv. Use the --root-user-action option if you know what you are doing and want to suppress this warning.

2.
FE bug: taking too many resources

3.
podman logs -f notelite-agent-celery        
onnxruntime cpuid_info warning: Unknown CPU vendor. cpuinfo_vendor value: 0

4.
roles and permissions in podman

5.
async logging

6.
perplexity's feedback for my models(llama 3.1B)
Your bot is doing solid reading comprehension and paraphrasing. The main thing to watch for is:
  Directional mix‑ups (e.g., accidentally attributing “soft, irregular forms” to Baskerville instead of to older fonts).
  Over‑quoting tone (like “according to the story”) if you want a more natural, concise style.

7.
deployment solutions, esp. models

8.
concurrency support - auto scaling to multiple requests simultaneously

9.
Maintain Chunk Order: Do you want a "Stress Test" story where two different people give conflicting information to see how the model decides which one to trust?




so my plan for my blog app: 

user edits their post -> BE(updates DB + sends raw text and metadata to queue) -> RAG(takes text from queue + chunks -> for each chunk generates summary + generates embeddings for both chunk and chunk summary + stores in 2 indexed collection with metadata) -> stores chunks with its summary -> if overall_summary is present, then add that one as well

for example: "chunk_summaries, overall_summary = handle_chunk_summaries(chunks)"

User asks questions -> retrieval service -> embeds query -> queries vector db with chunk_vec index and summary_vec index with "using" argument, combine and dedup results -> rerank -> top-k -> LLM -> response


### PLAN:
    2 collections
    - doc_summaries: doc_id, text=(overall_summary+keywords+questions), metadata
    - doc_chunks: doc_id, text=(chunk), metadata(keywords, **metadata)

    - Ingestion:
        for each chunk
            - extract + merge all keywords: yake + spacy
            - combine chunks until I get a max token cap set for a single summary chunk;
                eg., chunk1(10 tokens) + chunk2(30 tokens), chunk3(100 tokens);
                if cap is 50, then one summary chunk would be chunk1 + chunk2 and then make a api call to summarize the combined chunk; collect all combined chunk summaries
            - if chunk is < 30, then no summary

        - iteratively repeat the process until on final summary chunk exist, later create a vector document for the (overall_summary + merged_keywords)
        - generate questions with the final summary and tag along while ingesting the chunk

    Retrieval:
        - query doc_summaries collection
        - filter docs which has score > 0.8, filtered_docs
        - if len(filtered_docs) > 3, then extract doc_ids and query doc_chunks, with those doc_ids
        - else, fallback to query all doc_chunks
        - rerank with RFF
        - combine all chunk text and summary text and give to llm


### intent processing
> intent-aware retrieval: opinion, advice, comparision, informational
> use llm to parse user query
> minmal viable schema
{
    "topics": [],
    "keywords": [],
    "entities": [],
    "intent": "",
    "sentiment": "",
    "parent_summary": ""
}

eg.,
{
  "intent": "fact_lookup | troubleshooting | comparison | exploratory",
  "entities": {
      "technologies": [],
      "concepts": [],
      "errors": [],
  },
  "keywords": [],
  "expanded_queries": [],
  "filters": {},
}
eg.,
“auth issue in react”

> parsed output:
{
  "intent": "troubleshooting",
  "entities": {
      "technologies": ["React"],
      "concepts": ["authentication"],
  },
  "keywords": ["auth", "issue"],
  "expanded_queries": [
      "react authentication error",
      "jwt auth issue react app",
      "react login not working"
  ]
}

> Vague queries need recall > precision
len(query_entities) == 0 and len(query_topics) <= 1: is_vague = True
{
    "query_topics": [],
    "query_entities": [],
    "query_intent": str,
    "query_sentiment": optional
}

“Query → Hypothesis Generation”

> Also add this to data points while ingestion
1.
...data_points
"intent": str,                # inferred from chunk
"sentiment": str,             # positive | negative | neutral

2.
use llm to generate:
"Assign 1–3 high-level topics for this text"

3.
use spaCy to extract entities, like
brands (“Nike”)
places (“New York”)
products (“iPhone 15”)
people (optional)

4.
Classify chunks into:
intent ∈ {
    "opinion",        # subjective views
    "experience",     # personal story
    "advice",         # recommendations
    "comparison",     # vs style
    "informational"   # neutral facts
}





rbhaviri@RBHAVIRI-M-XQTX _others % cd simpleNote/v2/notelite_inference 
rbhaviri@RBHAVIRI-M-XQTX notelite_inference % ./build/inference_api 
Registering routes (mode: summarization)...
  GET  /ping
  GET  /health
  GET  /v1/models
  POST /v1/chat/completions  (OpenAI-compatible; ?purpose=summary|query_parsing)
Server: http://0.0.0.0:8081 (mode=summarization)
rbhaviri@RBHAVIRI-M-XQTX notelite_inference % cd build                           
rbhaviri@RBHAVIRI-M-XQTX build % cmake .. -DCMAKE_BUILD_TYPE=Release

CMAKE_BUILD_TYPE=Release
-- Warning: ccache not found - consider installing it for faster compilation or disable this warning with GGML_CCACHE=OFF
-- CMAKE_SYSTEM_PROCESSOR: arm64
-- GGML_SYSTEM_ARCH: ARM
-- Including CPU backend
-- Accelerate framework found
-- Could NOT find OpenMP_C (missing: OpenMP_C_FLAGS OpenMP_C_LIB_NAMES) 
-- Could NOT find OpenMP_CXX (missing: OpenMP_CXX_FLAGS OpenMP_CXX_LIB_NAMES) 
-- Could NOT find OpenMP (missing: OpenMP_C_FOUND OpenMP_CXX_FOUND) 
CMake Warning at llama.cpp/ggml/src/ggml-cpu/CMakeLists.txt:84 (message):
  OpenMP not found
Call Stack (most recent call first):
  llama.cpp/ggml/src/CMakeLists.txt:445 (ggml_add_cpu_backend_variant_impl)


-- ARM detected
CMake Warning at llama.cpp/ggml/src/ggml-cpu/CMakeLists.txt:146 (message):
  ARM -march/-mcpu not found, -mcpu=native will be used
Call Stack (most recent call first):
  llama.cpp/ggml/src/CMakeLists.txt:445 (ggml_add_cpu_backend_variant_impl)


-- Checking for ARM features using flags:
--   -U__ARM_FEATURE_SVE
--   -U__ARM_FEATURE_SME
--   -mcpu=native+dotprod+i8mm+nosve+nosme
-- Adding CPU backend variant ggml-cpu: -U__ARM_FEATURE_SVE;-U__ARM_FEATURE_SME;-mcpu=native+dotprod+i8mm+nosve+nosme 
-- BLAS found, Libraries: /Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/System/Library/Frameworks/Accelerate.framework
-- BLAS found, Includes: 
-- Including BLAS backend
-- Metal framework found
-- Including METAL backend
-- ggml version: 0.9.8
-- ggml commit:  49bfddeca
-- Configuring done (1.2s)
-- Generating done (0.1s)
-- Build files have been written to: /Users/rbhaviri/Desktop/_others/simpleNote/v2/notelite_inference/build
rbhaviri@RBHAVIRI-M-XQTX build % make -j$(nproc)

zsh: command not found: nproc
[  5%] Built target ggml-base
[  6%] Built target ggml-blas
[ 11%] Built target ggml-metal
[ 20%] Built target ggml-cpu
[ 21%] Built target ggml
[ 97%] Built target llama
[ 97%] Building CXX object CMakeFiles/inference_api.dir/src/model_loader.cpp.o
[ 98%] Linking CXX executable inference_api
[100%] Built target inference_api
rbhaviri@RBHAVIRI-M-XQTX build % ./inference_api                    
Registering routes (mode: summarization)...
  GET  /ping
  GET  /health
  GET  /v1/models
  POST /v1/chat/completions  (OpenAI-compatible; ?purpose=summary|query_parsing)
Server: http://0.0.0.0:8081 (mode=summarization)


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
celery -A app.tasks.notes worker -Q note_size --loglevel=info

FE:
npm i
npm run dev

Tests
python -m pytest tests/ -v


TODOs:
So, to summarize, while generate summary for chunks, I will change the prompt to generate related questions and keywords and then format it like summary, related questiosn, keywords then embed whole text, 
while retrieval, user query first checks similarity with summary_vec which gives question to question matching as well + keywords, also store these in payload/metadata to filter these with filters,
also I will use scrore_threshold property first to check whether to relay on documents identified by summary chunks, if less than the threshold, fallback to search all chunk_vec


To make the fallback seamless in Qdrant, you have two ways to handle the score_threshold:
The "If/Else" Approach (Code Level):
Query summary_vec.
Check if results[0].score > 0.7 (or your chosen threshold).
If yes: Use those document IDs to filter a chunk_vec search.



Payload: {"keywords": ["RAG", "Vector Search", "Qdrant"], "doc_id": "A1"}
Why: This allows you to use Qdrant’s Match filter to find any document that contains a specific keyword, which is much faster than a text search.


- "Summarize the following text in 2 sentences. Then, list 3 diverse questions this text answers. Finally, provide 5 key entities/topics mentioned.
Format:
Summary: [text]
Questions: [q1, q2, q3]
Keywords: [k1, k2, k3, k4, k5]"

Devops:
If you are running Redis inside a Docker/Podman container, "binding to localhost" is usually handled by how you map your ports. To stay safe, ensure your port mapping looks like this in your docker-compose.yml or run command:
127.0.0.1:6379:6379 (This forces the container to only accept traffic from the host machine's loopback interface).


=> We could look at how to mask sensitive data (like emails or SSNs) before sending it to the LLM for embedding. Would that be a useful security layer for your project?

## SYSTEM DESIGN

Encryption/decryption flow
BE - QUEUE - AGENT
  FE --POST notes/-> BE
                     |-- extract notes from clear_json(tiptap), clear_text
                     |-- encrypt clear_text with Fernet, cipher_text
                     |-- encrypt clear_json with Fernet, cipher_json
                     |-- save cipher_text and cipher_json to db 
                     |----- instead of clear_text and clear_json
                     |-- send clear_text to agent ----------------> [ QUEUE ] ----> AGENT(with celery) picks task from the QUEUE
                                                                                      |-- chunks -> generate embeddings
                                                                                      |-- encrypt clear chunk text and attach it to points
                                                                                      |-- retrieval request -> top-k chunks -> decrypts chunk's text, combine it and give it to llm for processing

### CHAT STREAMING
FE ──POST /api/chat/stream──▶ Agent
                                │
                                ├─ 1. Create/reuse conversation via BE internal API
                                ├─ 2. Write-ahead: user msg + assistant msg (status=partial)
                                ├─ 3. Retrieve context from Qdrant
                                ├─ 4. Call inference (blocking)
                                ├─ 5. Stream response as SSE events (word-by-word)
                                └─ 6. Celery task: update assistant msg (status=complete)


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

- Conversations: (`/api/conversations`) · *requires auth*
  - `GET    /`                                   — List own conversations · newest first · `?skip=&limit=`
  - `POST   /`                                   — Create conversation
  - `GET    /{conv_id}`                          — Get conversation with all messages
  - `DELETE /{conv_id}`                          — Delete conversation and all messages

  - Internal (Agent → Backend) · *requires `X-Internal-Key` + `X-User-Id` headers*
    - `POST   /internal/`                          — Create conversation on behalf of user
    - `POST   /internal/{conv_id}/messages`        — Create message (write-ahead)
    - `PATCH  /internal/{conv_id}/messages/{msg_id}` — Update message (finalize after streaming)

#### Conversation request/response examples

**Create conversation**
```
POST /api/conversations/
Body:    { "title": "How does X work?" }
Response: { "success": true, "data": { "id": "uuid", "user_id": "uuid", "title": "...", "created_at": "...", "updated_at": "..." } }
```

**Get conversation with messages**
```
GET /api/conversations/{conv_id}
Response: { "success": true, "data": {
  "id": "uuid", "title": "...", "created_at": "...", "updated_at": "...",
  "messages": [
    { "id": "uuid", "role": "user", "content": "...", "status": "complete", "created_at": "..." },
    { "id": "uuid", "role": "assistant", "content": "...", "status": "complete",
      "model_used": "mistral-7b", "latency_ms": 1200, "tokens_used": 87,
      "sources_used": ["note_id_1", "note_id_2"], "created_at": "..." }
  ]
}}
```

**Create message (write-ahead, internal)**
```
POST /api/conversations/internal/{conv_id}/messages
Headers: X-Internal-Key: <secret>, X-User-Id: <user_uuid>
Body:    { "role": "assistant", "content": "", "status": "partial" }
Response: { "success": true, "data": { "id": "uuid", "role": "assistant", "status": "partial", ... } }
```

**Update message (finalize, internal)**
```
PATCH /api/conversations/internal/{conv_id}/messages/{msg_id}
Headers: X-Internal-Key: <secret>, X-User-Id: <user_uuid>
Body:    { "content": "Full answer...", "status": "complete", "latency_ms": 1200, "tokens_used": 87, "sources_used": ["note_id_1"] }
Response: { "success": true, "data": { "id": "uuid", "status": "complete", ... } }
```

### Agent chat endpoints

- Chat: (`/api`) · *requires `X-API-Key` header*
  - `POST /chat`                    — Single-turn RAG Q&A (non-streaming)
  - `POST /chat/stream`             — Streaming RAG Q&A with conversation persistence

#### Streaming chat request/response

**Request**
```
POST /api/chat/stream
Headers: X-API-Key: <agent_secret>
Body: {
  "query": "What did I write about project Zenith?",
  "k": 5,
  "user_id": "uuid",
  "role": "user",
  "tenant_id": "uuid",
  "conversation_id": null,
  "conversation_title": "Project Zenith notes"
}
```

**Response** (SSE stream, `Content-Type: text/event-stream`)
```
event: meta
data: {"conversation_id": "uuid", "message_id": "uuid", "user_message_id": "uuid"}

event: delta
data: {"content": "Based"}

event: delta
data: {"content": " on"}

event: delta
data: {"content": " your"}

event: delta
data: {"content": " notes,"}

...

event: done
data: {"latency_ms": 1200, "sources": ["note_id_1", "note_id_2"]}
```

**On error**
```
event: meta
data: {"conversation_id": "uuid", "message_id": "uuid", "user_message_id": "uuid"}

event: error
data: {"message": "Model failed to load"}

event: done
data: {"latency_ms": 500, "sources": []}
```



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
  - query vector DB with filters(user_id) - CLEAR
  - 

  <!-- - [edgecase] if low score like between 1 - 10%, then vague fallback to "could you elaborate on what you are referring to?" then give clarifying questions
  - [edgecase] if confidence score is still low but > 10%, then query vector DB over all the available notes, get top k, then summarize and give response -->



### Challenges:

**Was it a leak?**
Partially, yes — through a transaction state issue.

Without the explicit rollback() in the except branch, when a request raised an exception (e.g. duplicate-email on register), the session was closed with an uncommitted, dirty transaction still attached. SQLAlchemy's pool fires reset_on_return (a silent rollback) when the connection returns, but under high concurrency this reset adds latency. While the pool was waiting on those resets, new requests couldn't get connections — the pool drained.


**Keywords extractor:**
First Attempt: Caught everything (Stop words, fillers, fragments).
Second Attempt: Cleaned stop words but missed phrase logic (Caught "bad day", "long night").
Current Attempt: Success. extracts actual business and technical concepts while ignores the "fluff" and "vague endings."


{"text":"I cannot summarize without the text provided. Please give the text for me to summarize.","metadata":{"doc_id":"6946c8a4-c0ec-4462-a3dd-d3ed2b0f2b72-306d7544-f16d-4d1e-952f-fdf46ca4cdd6-78f61915-ce78-433d-a4c3-369749a6f15e","user_id":"6946c8a4-c0ec-4462-a3dd-d3ed2b0f2b72","tenant_id":"6946c8a4-c0ec-4462-a3dd-d3ed2b0f2b72","folder_id":"306d7544-f16d-4d1e-952f-fdf46ca4cdd6","note_id":"78f61915-ce78-433d-a4c3-369749a6f15e","folder_title":"Chapters","note_title":"Chapter 1: the super robot assistant","description":"","tags":"","chunk_id":0,"summary":"I cannot summarize without the text provided. Please give the text for me to summarize."}}


{"text":"th","metadata":{"doc_id":"6946c8a4-c0ec-4462-a3dd-d3ed2b0f2b72-306d7544-f16d-4d1e-952f-fdf46ca4cdd6-78f61915-ce78-433d-a4c3-369749a6f15e","user_id":"6946c8a4-c0ec-4462-a3dd-d3ed2b0f2b72","tenant_id":"6946c8a4-c0ec-4462-a3dd-d3ed2b0f2b72","folder_id":"306d7544-f16d-4d1e-952f-fdf46ca4cdd6","note_id":"78f61915-ce78-433d-a4c3-369749a6f15e","folder_title":"Chapters","note_title":"Chapter 1: the super robot assistant","description":"","tags":"","chunk_id":1,"summary":"The text is missing. Please provide the text for summarization."}}