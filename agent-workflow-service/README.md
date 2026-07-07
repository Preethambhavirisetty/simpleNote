# Agent Workflow Service

Standalone HTTP runtime for the planner → executor → reviewer workflow.

Default port: **5453**

## Quick start (local)

```bash
cd agent-workflow-service
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # edit LLM + MCP values
export PYTHONPATH=app
uvicorn app.main:app --host 0.0.0.0 --port 5453 --reload
```

Health:

```bash
curl http://127.0.0.1:5453/health
```

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness |
| POST | `/api/agent-workflow/run` | Sync run (YAML or inline config) |
| POST | `/api/agent-workflow/stream` | SSE stream (YAML or inline config) |
| POST | `/api/agent-workflow/run/runtime-bundle` | Sync run from Agent Studio runtime bundle |
| POST | `/api/agent-workflow/stream/runtime-bundle` | SSE stream from runtime bundle |
| POST | `/api/agent-workflow/resume` | Resume after destructive approval |

When `AGENT_WORKFLOW_API_KEY` is set, send header `X-API-Key: <key>`.

Debug trace: set `AGENT_WORKFLOW_DEBUG_TRACE=true` to include final-turn one-line workflow logs and token counts in sync `debug_trace` string arrays, sync `events`, and streaming `done.debug_trace` payloads.

## Postman example (YAML agent)

```http
POST http://127.0.0.1:5453/api/agent-workflow/stream
Content-Type: application/json

{
  "query": "List dashboards",
  "session_id": "postman-1",
  "config_path": "app/agent_workflow/agents/default.yaml"
}
```

## CLI (same engine, no HTTP)

```bash
export PYTHONPATH=app
python -m app.agent_workflow.main --config app/agent_workflow/agents/default.yaml "Hello"
```

## Container

```bash
podman build -t localhost/agent-workflow-service:latest .
podman run --rm -p 5453:5453 --env-file .env localhost/agent-workflow-service:latest
```

Or use `podman-compose.yml` in this directory.

## Tool index search (optional)

When Agent Studio connectors have more than six tools, tool metadata is embedded into per-connector Qdrant collections via **mcp-service** internal routes. At runtime, **agent-workflow** can search those collections before falling back to `tools/list` ranking.

Configure:

| Env | Service | Purpose |
|-----|---------|---------|
| `MCP_INTERNAL_KEY` | mcp-service, backend, agent-workflow | Shared secret for internal routes |
| `MCP_TOOL_INDEX_URL` | backend | Base URL of mcp-service (upsert/delete on connector test) |
| `TOOL_INDEX_MIN_TOOLS` | backend | Minimum tool count before indexing (default `6`) |
| `TOOL_INDEX_SEARCH_URL` | agent-workflow | Search endpoint (default mcp-service internal search) |
| `TOOL_INDEX_API_KEY` | agent-workflow | Sent as `X-Internal-Key` (falls back to `MCP_INTERNAL_KEY`) |

Runtime bundles include a `tool_discovery` block per MCP server when a connector is indexed. The workflow calls the search URL with:

```http
POST /internal/connector-tools/search
Content-Type: application/json
X-Internal-Key: <MCP_INTERNAL_KEY>

{
  "owner_user_id": "550e8400-e29b-41d4-a716-446655440000",
  "collections": ["ct_<owner_uuid>_<connector_uuid>"],
  "query": "user task or planner sub-goal",
  "limit": 8
}
```

Response:

```json
{
  "ok": true,
  "tools": [
    { "name": "tool_a", "description": "...", "score": 0.82 }
  ]
}
```

The workflow applies the agent tool allowlist after search. If search fails or the connector is not indexed, the workflow **defaults to fallback discovery** (`tools/list` + keyword ranking) without failing the run.


TODO:
Low — executor SRP. I deliberately did not do this one now, and I'd push back on doing it as part of a bugfix. You're right that executor.py still owns tool discovery, native calling, argument injection, schema validation, approval routing, loop breaking, truncation, scoring, and artifact creation — and tool_selection / tool_validation / artifact_builder / executor_loop is a sensible target decomposition. But it's a large, purely-structural refactor of the most complex node, it carries real regression risk, and the executor already has pre-existing failing tests (the native-mode ones) that would make it hard to distinguish refactor regressions from prior breakage. Since you flagged it non-urgent/long-term, the disciplined move is a dedicated follow-up PR with the native-mode tests green first, not folding it into this change. Happy to take that on separately if you want to prioritize it.

### Discussions:

2 things:
- for follow ups, does agent does semantic search for tools with the given query, right? so I think agent need to summarize conversation history provided, rephrase the question and then do semantic search against the tool, then it return much relevant tools, right? is it already implemented?
- agent loops goes on, at one point, it thinks more reasearch or exploration should happen, so, it has to summarize its memory so far, then it allows room for further reasearch, right? how can I implement that?


------ 
1. Tool search on follow-ups — partly there, with a real gap
How it works today:

The semantic search query is step_query, built mechanically in executor.py:612 as plan_step.title + plan_step.action + user_query. Conversation history is not in it, and there's no summarize/rephrase step feeding the search.
History does reach the LLMs indirectly: ContextBuilder adds a "Conversation history" section (last max_history_messages, head/tail-truncated) to the planner and executor prompts. So the planner writes history-aware step titles, and those flow into step_query.
In non-native mode, the executor LLM emits its own {"action":"search_tools","query":"…"} (executor.py:795), so it can already rephrase using the history it sees. That's your idea, done inline.
But your production config (default.yaml) sets native_tool_calling: true, and the native prefetch path (executor.py:350) searches with the raw mechanical step_query — no rephrasing, no history. So exactly the case you're worried about is the weakest one.
follow_up.py does detect follow-ups and infer which tools to re-run, but via regex keyword hints (dashboard→list_dashboards, etc.), not semantics.
So: no, the dedicated "summarize history → rephrase → semantic search" isn't implemented. The clean fix is a small query-builder step that, on follow-up turns, condenses recent history + the current question into one search string and uses it for the native prefetch (and as the default for non-native). It's cheap if you make it deterministic (concatenate + dedupe salient nouns), or one small LLM call if you want true rephrasing. I'd gate it behind the existing is_follow_up_query() so single-shot turns pay nothing.

2. Mid-loop memory summarization — not implemented; here's the shape I'd build
Today the loop doesn't summarize as it goes. Context is kept bounded by two blunt mechanisms: artifacts are pruned to max_retained_artifacts by composite score (low-score evidence is dropped, not compressed), and each turn's prompt is re-budgeted to max_context_tokens by ContextBuilder. fact_extractor runs once, terminally, after the executor is done — it's not available mid-loop to free up room.

A chat-summarizer / running-memory node is a good fit. Concretely:

Trigger, not every turn: when retained artifacts approach the cap, token budget is tight, or executor turns cross a threshold — so you don't pay an LLM call each iteration.
One LLM call that reads the current artifacts/tool results and returns a compact research_memo (confirmed facts, open questions, dead ends). Reuse the existing Fact provenance shape so downstream nodes treat memo items like any other fact.
Write it back to state (e.g. state["running_summary"]) and let ContextBuilder inject it as a high-priority section, then prune the now-summarized raw artifacts — that's what actually buys back context for more exploration.
Keep it bounded (cap invocations, like revision) so it can't loop.
The graph edge is small: an executor → summarizer → executor self-loop gated by a phase: "compacting" signal, mirroring how approval re-enters the executor. The risk to watch is fidelity loss (summarizing away a detail you later need), so keep provenance and don't discard source_refs.

3. Deterministic output formats — worth adding selectively, not wholesale
Right now formatting is almost entirely LLM-driven: the synthesizer writes prose, the finalizer re-renders mechanical drafts with another LLM call, and the only deterministic path is _fallback_from_facts() producing a flat bulleted list. No deterministic table/checklist rendering.

My take: don't replace the LLM for prose — it's genuinely better at narrative answers. But do add deterministic renderers for the cases where structure is known and LLMs are unreliable or wasteful: tables from raw_ref.rows/panels/tables (counts, IDs, columns), checklists from plan acceptance criteria, and "N items found" lists. Benefits: no hallucinated cell values, no truncated tables, and you skip an LLM call. The natural hook is draft_kind: add a "tabular" kind that the finalizer renders mechanically (you already special-case "mechanical" vs "llm" there), chosen when a tool returns clean structured rows. This pairs perfectly with the structured-facts contract we just wired — the same panels/rows/facts fields that survive compaction can drive a deterministic table.

------

rephrase_conversation_summary() -> uses conversation history + current query and rebuilds new user query(with pronouns replaced) so semantic tool search becomes obvious. right?

regarding runtime context(tool results, plan and others) summarizer, how about this, if a vector store is configured, can we create ref_id, index the current runtime context with embed text and ref_id as metadata. when later something is needed from the runtime context, it can semantic search for that data. but another question would be, how can it know if it need something from current runtime context? also is it good if we keep creating a collection for every runtime context(lives only during the current chat).

