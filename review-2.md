# Review 2 Fix Tasks

Use these tasks with `instructions/code-fix.md`.

General rules for the fixing agent:

- Fix one task at a time.
- Make the smallest production-safe change that fully resolves the issue.
- Do not refactor unrelated code.
- Preserve existing behavior unless the task explicitly requires changing it.
- Add or update focused tests for code-path fixes.
- After each task, report what changed, why it fixes the issue, assumptions, remaining risks, and tests run.

## Production Blockers

### Task 1: Stop note moves from duplicating and orphaning vector chunks

Severity: High

Locations:

- `notes.py:149-165`
- `orchestrator.py:216-222`

Goal:

Ensure moving a note between folders does not leave stale vector chunks indexed under the old folder-derived document id.

Problem:

The agent document id is currently derived from `user_id`, `folder_id`, and `note_id`. After a note move, ingestion writes chunks for the new folder id but does not delete chunks stored under the old folder id. This creates duplicate retrieval results, stale folder metadata, unbounded index growth, and possible deleted-note content retention.

Preferred fix:

Use a stable document identity that does not include `folder_id`, such as `user_id-note_id`, because folder membership is metadata rather than identity.

Minimum acceptable fix:

If changing document identity is too risky for the current release, delete the old `(user_id, old_folder_id, note_id)` document before upserting the moved note under the new id.

Acceptance criteria:

- A moved note has only one active vector document after re-ingestion.
- Deleting a moved note removes its indexed chunks.
- Retrieval no longer returns both old-folder and new-folder copies of the same note.
- Existing tests pass.
- Add a focused test or integration-level coverage for move re-ingestion cleanup.

Notes:

- If using the preferred stable id fix, document the migration or cleanup step needed for existing vectors.
- Keep folder title/path as payload metadata where needed for citations.

### Task 2: Validate folder ownership when creating notes

Severity: High

Location:

- `notes.py:85-96`

Goal:

Prevent users from creating notes inside folders owned by another user.

Problem:

`create()` writes `folder_id` from the request body directly. The database foreign key only verifies that the folder exists, not that it belongs to the authenticated user. This allows cross-user note placement, cross-user cascade deletion, and incorrect RAG folder metadata.

Recommended fix:

Before creating the note, load the folder with the authenticated `user_id`, using the same ownership guard pattern already used by note move. Return 404 or the existing not-found behavior if the folder does not belong to the user.

Acceptance criteria:

- A user cannot create a note in another user's folder.
- Creating a note in the user's own folder still works.
- Existing note creation behavior is preserved for valid requests.
- Add a focused authorization test for cross-user folder creation.

### Task 3: Execute production secret rotation checklist

Severity: Medium, release blocker by project policy

Locations:

- `SECRETS.md`
- `backend/.env`
- `notelite_agent/.env`
- Any deployed environment secret store or compose env files

Goal:

Ensure known development credentials are not used in production.

Problem:

`SECRETS.md` says seven credentials must be regenerated before production, but the known `AGENT_API_KEY` value and related credentials are still present in environment files.

Recommended fix:

Follow the `SECRETS.md` rotation checklist as a release gate. Rotate all listed credentials in the deployed environment and update local examples/templates only with placeholders.

Acceptance criteria:

- No production deployment uses the known reviewed secret values.
- `.env.example` files contain placeholders, not live credentials.
- The deployed backend and agent agree on the rotated internal key.
- The rotation steps are documented as completed.

Notes:

- Do not commit real rotated secrets.
- If this repository intentionally tracks local `.env` files, replace sensitive values with safe local-only placeholders unless the project requires otherwise.

### Task 4: Enable secure auth cookies in production config

Severity: Medium

Locations:

- `config.py:52-54`
- `podman-compose.yml`
- `.env.example` or equivalent env template

Goal:

Make production auth cookies secure by configuration.

Problem:

`COOKIE_SECURE` exists but is not enabled in compose or env templates. As shipped, production can still set auth cookies with `secure=False`.

Recommended fix:

Set `COOKIE_SECURE=true` for the backend production/container environment. Add the setting to env templates. If the code defaults are changed, keep local development ergonomics explicit and documented.

Acceptance criteria:

- Containerized production config sets `COOKIE_SECURE=true`.
- Env examples include `COOKIE_SECURE`.
- Local development can still intentionally opt out when using plain HTTP.
- Existing auth tests pass.

### Task 5: Fix backend Docker healthcheck endpoint

Severity: Medium

Location:

- `backend/Dockerfile:47-52`

Goal:

Make the backend container healthcheck probe a real readiness endpoint.

Problem:

The Docker healthcheck probes `GET /api/stats`, but no such route exists. Valid routes include `/api/health` and `/metrics`. The backend container is permanently unhealthy.

Recommended fix:

Change the healthcheck path to `/api/health`.

Acceptance criteria:

- Backend healthcheck uses an existing endpoint.
- The container can become healthy when the API is running.
- No unrelated Dockerfile changes are made.

## High-ROI Follow-Up Tasks

### Task 6: Prevent concurrent migration runners and handle pre-existing databases

Severity: Medium

Locations:

- `backend/Dockerfile:57`
- `podman-compose.yml`
- Existing backend migration entrypoint script
- Same pattern on `agent` / `agent-celery`, if present

Goal:

Make database migrations reliable during deploys and avoid crash-loops on existing databases created before Alembic.

Problem:

The API container and Celery worker both run `alembic upgrade head` at startup because they share the same image entrypoint. This creates a migration race. Also, an existing `create_all` database with tables but no Alembic version row fails on `CREATE TABLE users`, retries 30 times, and crash-loops.

Recommended fix:

Run migrations from exactly one place, such as only the API container or a dedicated one-shot migration step. Bypass the migration entrypoint for workers. Also detect the populated-but-unstamped database case and either stamp head safely or fail fast with a clear instruction.

Acceptance criteria:

- Only one backend process runs migrations during compose startup.
- Workers do not race the API migration runner.
- A pre-existing populated database no longer retries the same failing migration 30 times.
- The README/runbook and automation agree.

### Task 7: Isolate streaming event state per chat request

Severity: Medium

Locations:

- `chat/routes.py:27`
- `api_client.py:14`
- `backend_conversation_client.py:82-86`

Goal:

Prevent concurrent chat requests from mixing or stealing each other's event logs.

Problem:

The singleton `StreamingService` owns a singleton `BackendConversationClient`, which owns an `APIClient` with a shared mutable `events` list. Concurrent requests append to and drain the same list, making telemetry unreliable under load.

Recommended fix:

Create request-scoped event storage. Options include constructing a `BackendConversationClient` per request while sharing an underlying HTTP connection pool, or returning events from each API call instead of accumulating them on the client.

Acceptance criteria:

- Events from one chat request cannot appear in another chat request.
- Concurrent chat requests cannot drain each other's events.
- HTTP connection reuse is preserved where practical.
- Add a focused concurrency/unit test for event isolation.

### Task 8: Fix cookie-auth user id extraction and trusted user-id headers

Severity: Medium

Location:

- `main.py:43-58`

Goal:

Restore per-user log attribution for cookie-authenticated browser requests and avoid spoofed user ids in logs.

Problem:

The auth cookie stores `"Bearer <jwt>"`, but `_extract_user_id` decodes the raw cookie value without stripping the prefix. Browser requests therefore log as `anonymous`. Also, `X-User-Id` is trusted from any client for log attribution.

Recommended fix:

Reuse the existing token decoding path that handles the Bearer prefix. Only honor `X-User-Id` when the request also carries a valid `X-Internal-Key`.

Acceptance criteria:

- Cookie-authenticated browser requests log the real user id.
- Invalid cookies still log as anonymous.
- Public clients cannot spoof `X-User-Id`.
- Internal service requests can still provide trusted user attribution.

### Task 9: Close ingestion version check race before vector replacement

Severity: Medium

Locations:

- `orchestrator.py:37-39`
- `orchestrator.py:180-196`

Goal:

Prevent stale ingestion jobs from overwriting newer note vectors.

Problem:

The version guard checks staleness only at task start. If worker A starts processing version 2, worker B later processes version 3, and worker A writes last, stale version 2 artifacts can replace current content.

Recommended fix:

Re-check the note version immediately before `replace_index_chunks` / `replace_document`. If the payload version is no longer current, skip the write. A stronger alternative is to stamp version into vector payloads and make replacement conditional.

Acceptance criteria:

- A stale ingestion job cannot write vectors after a newer version has completed.
- Current-version ingestion still writes normally.
- Add focused test coverage for the late stale-write case.

### Task 10: Propagate trace ids through Celery and reject public trace injection

Severity: Low

Locations:

- `conversation.py:111`
- `ingestion_tasks.py`
- `main.py:63`
- nginx or proxy config, if present

Goal:

Keep async work correlated with the originating request without allowing public clients to inject arbitrary trace ids.

Problem:

HTTP calls now share trace ids, but Celery task payloads do not carry them. Async ingestion and persistence logs therefore get fresh trace contexts. Separately, inbound `X-Trace-Id` from public clients is trusted.

Recommended fix:

Pass `trace_id` in Celery task payloads and bind it in workers. Strip or ignore inbound public `X-Trace-Id`; only trusted internal hops should preserve it.

Acceptance criteria:

- Chat and note-save async logs share the originating trace id.
- Public clients cannot force arbitrary trace ids into logs.
- Internal service-to-service trace propagation still works.

## Remaining Carry-Over Tasks

### Task 11: Add reconciliation for Postgres and Qdrant drift

Severity: Medium

Goal:

Detect and repair cases where Postgres commits succeed but vector dispatch or indexing fails.

Acceptance criteria:

- There is a documented or automated reconciliation path for note records and indexed vectors.
- Failed enqueue/index operations can be discovered and retried.

### Task 12: Improve agent HTTP scalability

Severity: High before scale

Goal:

Remove the dominant scaling bottleneck from synchronous LLM, embedding, and rerank HTTP calls that create new connections per call.

Acceptance criteria:

- HTTP clients are reused where safe.
- Timeouts remain explicit.
- Streaming does not unnecessarily pin scarce worker resources.
- Changes are compatible with future LangGraph orchestration.

### Task 13: Revisit HyDE timeout behavior

Severity: Medium

Goal:

Avoid consistently wasting about two seconds on HyDE completions that are very unlikely to finish inside the configured timeout.

Acceptance criteria:

- HyDE timeout and token budget are aligned.
- Query latency improves or failure behavior is intentionally documented.

### Task 14: Broaden `persist_message` retry coverage

Severity: Medium

Goal:

Ensure transient backend failures do not leave assistant messages permanently partial and excluded from future history.

Acceptance criteria:

- Retry policy covers relevant HTTP/client/server failure classes.
- Non-retryable failures are still surfaced clearly.
- Add focused retry behavior coverage.

### Task 15: Clean up low-priority leftovers

Severity: Low

Goals:

- Reassess `compute_note_size` task overhead.
- Remove or justify dead `get_auth_user_id` code in conversation endpoints.

Acceptance criteria:

- Either remove unused code safely or document why it remains.
- No public behavior changes unless explicitly intended.
