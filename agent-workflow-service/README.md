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

