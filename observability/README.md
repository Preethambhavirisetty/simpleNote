# Agent Log Tracker

A minimal log system for an agent app. Sprinkle log lines anywhere in your code;
see the whole flow for one user question — from ask to final answer — in a
dashboard. Among those lines, mark selected values as **tracked fields** that you
can filter and aggregate on, and add new ones without touching the schema.

```
your agent  ──POST──▶  FastAPI  ──▶  MySQL (4 tables)  ◀──  React dashboard
```

## Quick start

```bash
make install      # venv + npm deps
make up           # MySQL 8.4 in podman, on :3307
make migrate      # create the 4 tables
make api          # backend on :8000        (in one terminal)
make seed         # 200 demo runs           (in another)
make ui           # dashboard on :5173
```

Then open <http://localhost:5173>. `make dev` runs the API and UI together.

## The idea

Two kinds of log content, and the whole design hinges on the split.

**Ordinary log lines** — `"cache miss for key cat:9510"`, `"trimmed 59 messages
from history"`. High volume, read as a stream, there to understand what a
specific piece of code did. These go in `logs`.

**Tracked fields** — `playbook`, `resource`, `operation`, `llm_latency_ms`,
`input_tokens`, `score`, `conversation_state`, `memory`, `tool_latency_ms`.
These you want to *query*: "average latency by playbook", "runs where score <
0.5". They go in `tracked_fields`, one row per value, with **separately indexed
text and numeric columns**.

That second table is why the field set can grow freely. A new tracked name is a
new row, not a migration:

```python
run.track(retrieval_hit_rate=0.82)   # never seen before -- just works
```

It self-registers in `field_defs`, appears in the dashboard, becomes filterable
(`?f.retrieval_hit_rate.gt=0.5`) and chartable, all with no code or schema
change. That is the acceptance test for the design, and it's covered in
`backend/tests/test_api.py::test_a_brand_new_field_name_needs_no_migration`.

## Logging from your agent

```python
import agentlog                      # sdk/agentlog.py

run = agentlog.start(question=q, conversation_id=cid)

run.info("matched %d candidates", n, phase="resolve_playbook")
run.debug("scoring candidates", phase="resolve_playbook", data={"scores": scores})
run.track(playbook="incident_triage", score=0.91)

with run.timed("tool", "k8s.describe_pod") as t:       # times the block
    result = k8s.describe_pod(ns, name)
    t.track(tool_name="k8s.describe_pod", tool_rows=len(result))

run.error("tool timeout, retry 1/3", phase="tool")
run.finish(final_answer=answer)
```

`run` is also a context manager — `with agentlog.start(...) as run:` finishes it
for you and records the exception if the block raises.

The logger buffers on a bounded queue and flushes from a daemon thread, so it
**never blocks or crashes your agent**. If the queue overflows it drops the
oldest lines and reports the count; if the service is unreachable it can spill to
a fallback file. `seq` is assigned client-side under a lock, so ordering survives
concurrency and out-of-order HTTP delivery.

Values route themselves by Python type: strings → `value_text`, numbers and
bools → `value_num`, dicts and lists → `value_json`. Units and aggregates are
inferred from the name (`_ms` → milliseconds and sums, `score` → averages), and
you can override either in the UI or via `PATCH /api/v1/fields/{name}`.

If you'd rather not use the SDK, POST the wire format directly — see
`POST /api/v1/runs/{run_key}/logs` below.

## Schema

Four tables. `DATETIME(6)` UTC everywhere (never `TIMESTAMP` — it silently
converts against the session timezone, which differs between your app, the
container, and a CLI). `seq` is the ordering authority, never the timestamp.

| Table | What it holds |
|---|---|
| `runs` | one user question → one final answer, plus derived counters |
| `logs` | the flat ordered stream; `UNIQUE (run_id, seq)` |
| `tracked_fields` | one row per tracked value; indexed text + numeric columns |
| `field_defs` | registry of field names, auto-created on first sighting |

Two details worth knowing:

`UNIQUE (run_id, seq)` on `logs` does double duty — it's the display order *and*
free idempotency. Re-POSTing a batch is a no-op, which is what makes retries
safe. The counters on `runs` are **recomputed** from the logs rather than
incremented, so a replayed batch can never double-count.

`tracked_fields` has three value columns rather than one JSON blob because MySQL
JSON columns are **not directly indexable** — a single JSON column would turn
every `GROUP BY` and every range filter into a full scan.

## API

Base path `/api/v1`. Full OpenAPI at <http://localhost:8000/docs>.

**Write**

| | |
|---|---|
| `POST /runs` | start or upsert a run (idempotent on `run_key`) |
| `POST /runs/{run_key}/logs` | append a batch; each line may carry `track` |
| `POST /runs/{run_key}/finish` | set status, final answer, duration |
| `PATCH /fields/{name}` | edit a field's label, unit, `pinned`, `aggregate` |

```jsonc
// POST /api/v1/runs/{run_key}/logs
{ "logs": [
  { "seq": 12, "level": "INFO", "phase": "resolve_playbook",
    "message": "selected playbook", "source": "planner.py:142",
    "track": { "playbook": "incident_triage", "score": 0.91 } },
  { "seq": 13, "level": "DEBUG", "phase": "llm", "message": "call complete",
    "duration_ms": 842, "data": { "stop_reason": "tool_use" },
    "track": { "model": "sample-model", "input_tokens": 4210 } }
] }
```

**Read**

| | |
|---|---|
| `GET /runs` | filters below, keyset pagination |
| `GET /runs/{run_key}` | header + every tracked field, collapsed by its aggregate |
| `GET /runs/{run_key}/logs` | `?level=WARN&phase=llm&q=timeout&after_seq=0` |
| `GET /runs/{run_key}/phases` | per-phase counts, for the filter chips |
| `GET /fields` | the registry |
| `GET /stats/overview` | run counts, error rate, p50/p95 duration |
| `GET /stats/fields/{name}` | `?agg=avg&group_by=playbook` or `?bucket=day` |
| `GET /stats/phases`, `/stats/timeseries` | rollups |
| `GET /conversations/{id}/runs` | every run in one conversation |
| `DELETE /runs/{run_key}` | cascades to logs and tracked fields |

`GET /runs` takes `status`, `conversation_id`, `q`, `phase`, `has_errors`,
`from`, `to` — **plus a filter on any tracked field**:

```
GET /api/v1/runs?f.playbook=incident_triage&f.llm_latency_ms.gt=800&f.score.lt=0.5
```

Operators: `eq` (default), `ne`, `gt`, `gte`, `lt`, `lte`, `contains`, `in`,
`exists`. Each becomes a correlated `EXISTS` against `tracked_fields`, so any
number of them combine without a join explosion.

## Dashboard

- **Runs** — stat tiles, filter bar with a builder for tracked-field filters, and
  a table whose columns are whichever fields you've pinned (★ in the run view).
- **Run detail** — the log stream on the left (level filter, phase chips, search,
  every row expandable for `data` and `source`) and the tracked-field panel on
  the right, with sparklines for repeated values and jump-to-line links.
- **Stats** — a field explorer: pick any tracked field, an aggregate, and an
  optional group-by. Plus log volume by phase.

Light and dark, following the OS with a manual override. Log level is always
icon + word + colour, never colour alone; phase colours come from a validated
categorical palette with a ≥8 CVD ΔE separation between adjacent hues.

## Layout

```
infra/podman/run-mysql.sh   podman run (podman-compose isn't installed here)
infra/mysql/my.cnf          utf8mb4, UTC, buffer_pool tuned for a 2 GiB VM
db/migrations/000{1..4}.sql one table each
db/migrate.sh               applies them, records in schema_migrations
sdk/agentlog.py             the logger you import into your agent
backend/app/
  api/v1/{ingest,runs,logs,fields,stats}.py
  services/field_router.py  value -> column, unit/aggregate inference
  services/filters.py       ?f.name.op=value -> correlated EXISTS
  seed/{generate,scenarios,vocab}.py
frontend/src/
  pages/{RunsPage,RunDetailPage,ConversationPage,StatsPage}.jsx
  components/{LogStream,TrackedPanel,FieldFilters,Primitives}.jsx
```

## Testing

```bash
make test     # 63 backend tests against a scratch agentlog_test database
make smoke    # renders every page in Chrome, fails on any console error
```

Integration tests run against real MySQL, not a stub — the behaviour worth
testing (`ON DUPLICATE KEY` idempotency, `DECIMAL` routing, correlated `EXISTS`)
is MySQL's behaviour, so a fake would prove nothing.

The seed generator writes through the HTTP API rather than straight to MySQL,
which makes it an integration test too: it shuffles lines within each batch and
re-sends ~5% of batches, continuously proving that ordering comes from `seq` and
that replays deduplicate.

## Notes on this environment

- `podman-compose` isn't installed, so `infra/podman/run-mysql.sh` uses plain
  `podman run`. MySQL is on **:3307** to stay clear of any local install.
- The podman VM has 2 GiB of RAM, so `innodb_buffer_pool_size` is 512M.
- `make smoke` uses your installed Google Chrome via Playwright's `channel`
  option, so it needs no browser download.
