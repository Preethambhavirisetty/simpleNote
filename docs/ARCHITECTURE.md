# Agent Workflow Service — Architecture & Working Guide

A verbal, code-free walkthrough of how the service works: the concepts, the graph, every node, the supporting subsystems, the optimizations, and how to actually use it. Function and class names are called out inline so you can jump to the source.

---

## 1. What this service is

The Agent Workflow Service is a tool-using LLM agent built on **LangGraph**. Given a user request, it plans, discovers and calls tools (over the **Model Context Protocol**, MCP), compresses the evidence it gathers into compact facts, writes one grounded answer, optionally has that answer reviewed and revised, and renders a final response. It exposes both an HTTP API (FastAPI) and a Python library surface (the `AgentEngine` class).

The core design philosophy is **separation of concerns across a small, bounded graph**: each node owns exactly one phase of work, loops are capped so the agent can never spin forever, and evidence is progressively compressed so the model never drowns in raw tool output. This is what keeps the agent stable and cheap compared with a single mega-prompt loop.

---

## 2. The mental model

Think of a single request as a state object (`AgentState`) flowing through a graph of nodes. Each node reads the state, does one job, and returns a partial update that LangGraph merges back in. A field called `phase` (a string like `"planning"`, `"executing"`, `"reviewing"`, `"done"`) is the primary signal the routing functions use to decide where to go next.

The normal path is:

**planner → executor loop → (summarizer detours) → fact_extractor → synthesizer → reviewer? → revision? → finalizer**

- **planner** turns the request into explicit steps.
- **executor** is the only node that touches tools; it loops, gathering evidence as artifacts.
- **summarizer** is a mid-loop detour that compresses memory when artifacts pile up.
- **fact_extractor** deterministically distills artifacts into small facts.
- **synthesizer** writes the one prose answer from facts.
- **reviewer** judges that answer (only when risk warrants it).
- **revision** rewrites once if the reviewer asks.
- **finalizer** renders or reuses the terminal answer.

Everything else in the codebase exists to support that pipeline: context assembly, truncation, scoring, tool discovery, configuration, caching, checkpointing, and telemetry.

---

## 3. The request lifecycle end to end

The entry point is the `AgentEngine` class (in `engine.py`). It is a **compile-once runtime**: the LangGraph graph is built a single time and reused across requests. Its public methods are `run` (synchronous), `stream` (server-sent events), `resume` and `resume_stream` (continue a paused approval).

A single `run` proceeds like this:

1. **Validation.** `_validate_request` runs the incoming `RunRequest` through the `RunRequestModel` pydantic schema. This strips prototype-pollution keys and enforces limits before anything executes.

2. **Fast-path check.** `_can_fast_path` decides whether the query is trivial enough to answer with one direct LLM call and *no graph at all* (see §8, Fast-path router). If so, `_fast_path_result` returns immediately.

3. **Session preparation.** `_prepare_session` loads any persisted cross-turn artifacts and resolves follow-up policy (see §7 and §9).

4. **Initial state.** `_initial_state` builds the starting `AgentState`: the user query, a deterministic `search_query` fallback (via `build_search_query`), history, and either an empty plan (planner enabled) or a one-step plan (planner disabled).

5. **Graph execution.** The engine streams updates out of the compiled graph and folds them into local state with `_pump`, which also translates internal node events into host/API events via `map_graph_update`.

6. **Termination.** `_result_from_state` assembles a `RunResult`. `_persist_session_artifacts` saves artifacts for the next turn (if enabled), `_cleanup_thread_if_terminal` deletes the checkpoint unless the run paused for approval, and `_attach_usage_event` appends token-usage telemetry.

The streaming variant (`stream`) is the same pipeline but yields incremental events — status, plan, tool activity, answer deltas, and a final `done` — as they happen.

---

## 4. The graph and its nodes

The graph is assembled in `build_graph` (`graph.py`). Nodes are wired with conditional edges whose routing functions read `phase`. Below is each node and what it actually does.

### 4.1 Planner — `planner_node`

The planner (`nodes/planner.py`) makes the smallest practical plan. It builds its prompt through `ContextBuilder` (so it sees the request and history), calls the LLM, and parses the markdown reply with `parse_plan_markdown` into a structured `Plan` (goal, steps, acceptance criteria, and a **search query rewrite** — see §6.1). It returns `phase: "executing"`.

Two important behaviors:
- If planning is disabled, it returns early with a deterministic `search_query` so the executor still gets a good retrieval query.
- If the LLM call exceeds `llm_timeout_seconds`, it degrades gracefully to a timeout answer rather than hanging (all LLM calls in the service are wrapped this way — see §5.7).

### 4.2 Executor — `executor_node`

The executor (`nodes/executor.py`) is the largest node and the **only one that orchestrates tools**. Each invocation is one "turn": it picks a single action and returns. The action comes either from a native tool-call response or from a JSON action the LLM emits (`search_tools`, `call_tool`, `finish_step`, or `draft_answer`), parsed by `parse_executor_action`.

Its responsibilities, all bounded by policy:

- **Tool discovery.** On a `search_tools` action it calls the tool provider's `search_tools`. Results are cached by query in `tool_discovery_cache` so a repeated search is free (`_cache_key`).
- **Native tool calling.** When the model supports it (`native_tool_calling`), `_prefetch_candidate_tools` fetches candidates up front and `_native_tool_specs` exposes them as OpenAI-style tool specs, so the model calls a tool directly without a separate search round-trip. `_complete_with_tools_llm` runs that turn; if the provider rejects the tools contract, it falls back to the JSON action path.
- **Argument validation.** Before any call, `_validate_tool_arguments` checks the arguments against the tool's JSON schema (required fields, basic types). Invalid calls are recorded (`_record_invalid_tool_arguments`) rather than executed.
- **Argument injection.** `_apply_argument_injection` fills tool arguments from the runtime context using dotted paths (e.g. a tenant id), resolved safely by `resolve_context_path` (which blocks `__proto__`/`prototype` traversal).
- **Policy gates.** `_is_tool_allowed` / `_filter_candidates_by_policy` enforce allowlists and denylists.
- **Destructive approval.** `_execute_tool_call_action` checks `destructive_tools`. A destructive call either runs a synchronous approver callback or pauses the whole graph at an interrupt (see §4.3). A call denied once is not re-asked (`_was_denied`, `_record_denial`).
- **Tool execution and recording.** `_run_tool_and_record` calls the tool under a deadline, truncates the result (`truncate_tool_result`), scores it (`score_artifact`), and appends an `Artifact` plus a `ToolCallRecord`. Both records carry `step_index` and `replan_id`.
- **Loop breaking.** Repeated `search_tools` with candidates already in hand is detected (`_search_repeat_counter`) and forced forward, so the model cannot loop on discovery.
- **Duplicate / required-tool tracking.** `_called_tools_for_step` computes which tools already ran for the current step, reading **both** artifacts and `tool_calls` (this dual source is deliberate — see §6.5).
- **Retention.** `_prune_artifacts` and `_prune_tool_calls` keep only the best/most-recent records within `max_retained_artifacts` / `max_retained_tool_calls`.

When the last plan step finishes, the executor hands off with `phase: "fact_extracting"` — it never writes the final answer itself.

### 4.3 Approval — `approval_node`

The approval node (`nodes/approval.py`) exists only for destructive tools. When the executor pauses, LangGraph's checkpointer records the state and emits a `pending_approval`. A host later calls `resume(thread_id, approved=True|False)`; the graph continues from the checkpoint, and the approval node either executes the pending tool (reusing the executor's `_run_tool_and_record`) or records the denial, then routes back to the executor. This is the service's **human-in-the-loop** mechanism, and it is durable across process restarts when a real checkpointer is configured.

### 4.4 Summarizer — `summarizer_node`

The summarizer (`nodes/summarizer.py`) is a **mid-loop memory-compaction detour** (see §6.2). When retained artifacts approach the cap, the routing function `_should_compact` sends the executor loop here. It makes one LLM call to fold the lower-scoring artifacts into a compact `running_summary` memo, keeps the top-scoring artifacts verbatim, drops the folded ones to free context, records structured provenance in `summary_sources`, and returns control to the executor. It is bounded by `summary.max_cycles` and falls back to a deterministic memo (`_fallback_memo`) on timeout.

### 4.5 Fact extractor — `fact_extractor_node`

The fact extractor (`nodes/fact_extractor.py`) is **deterministic on purpose** (no LLM). It converts artifacts into small, provenance-bearing `Fact` objects so the downstream authoring nodes reason over compact claims, not raw payloads. It prefers structured facts a tool supplies (the fact contract, §6.4), then generic collections, then falls back to splitting artifact summaries into lines. It also seeds facts from `running_summary` (`_memory_facts`) so summarized-away evidence still reaches synthesis.

### 4.6 Synthesizer — `synthesizer_node`

The synthesizer (`nodes/synthesizer.py`) is the **single normal authoring pass**. It writes one draft answer from facts only, tagging it with a `draft_kind` (`"llm"` prose, `"mechanical"` deterministic dump, or `"executor_draft"`). It emits an event on every path (`completed`, `skipped`, `fallback`, `timeout`) so streaming always shows synthesis activity. Crucially, it uses `_done_or_reviewing` to decide whether the draft needs a reviewer at all — clean runs skip straight to finalization (risk-gating, §8).

### 4.7 Reviewer — `reviewer_node`

The reviewer (`nodes/reviewer.py`) is a **judge only** — it never rewrites the answer. It returns a verdict (`APPROVE`, `REVISE`, `REJECT`) plus issues and required changes. Parsing is layered and robust (`_parse_review`): JSON first, then markdown (`parse_review_markdown`), then a safe `REVISE` default with a `reviewer.parse_failed` event. Before it accepts an `APPROVE`, it runs deterministic `_completion_gaps` checks (e.g. "the user asked about cards but no card evidence exists") that can override an over-eager approval into a `REVISE`. It is bounded by `max_cycles`.

### 4.8 Revision — `revision_node`

The revision node (`nodes/revision.py`) applies exactly **one** bounded rewrite using the same facts and the reviewer's issues. It calls no tools. If facts are insufficient, it is instructed to state the limitation rather than invent. After it runs, control goes straight to the finalizer — there is deliberately **no edge back to the executor**, which is what prevents the classic review→re-execute spiral.

### 4.9 Finalizer — `finalizer_node`

The finalizer (`nodes/finalizer.py`) produces the terminal answer. Its optimization: it **reuses** an LLM-written prose draft as-is (a second render would cost a full round-trip for no gain) and only spends an LLM call to render *mechanical* drafts. It can enforce grounding (`_ensure_grounding`) by appending source citations, drawing on both live artifacts and the summarizer's `summary_sources` sidecar (§6.6). If it is ever reached in an unexpected phase, it finalizes defensively with an error event instead of ending on an empty response.

### 4.10 Routing

Routing functions are pure functions of state: `route_after_start`, `route_after_planner`, `route_after_executor`, `route_after_synthesizer`, `route_after_reviewer`, plus the `_should_compact` predicate. Two design rules are enforced here:

- Every terminal path funnels through the **finalizer** (so the terminal `done` event is emitted exactly once, from the finalizer's update — see §6.7).
- Unknown/unexpected phases route to the finalizer rather than silently ending, so clients never get an empty response.

---

## 5. Supporting subsystems

### 5.1 State model — `state.py`

`AgentState` is the `TypedDict` that flows through the graph. Key fields: `user_query`, `search_query`, `plan`, `current_step_index`, `candidate_tools`, `tool_discovery_cache`, `artifacts`, `tool_calls`, `facts`, `draft_answer`, `draft_kind`, `review`, `review_feedback`, `running_summary`, `summary_sources`, `iteration`, `phase`, `final_answer`, `error`, `pending_destructive`. Supporting shapes: `Plan`, `PlanStep`, `Artifact`, `Fact`, `ReviewResult`, `ToolCallRecord`, `IterationCounters`. The counters (`executor_turns`, `review_cycles`, `revision_cycles`, `summaries`, `replans`) are what cap the loops.

### 5.2 Context assembly — `context/builder.py`

`ContextBuilder.build` assembles the prompt for a given role (planner, executor, reviewer). It gathers candidate sections (user request, plan, candidate tools, artifacts, recent tool calls, reviewer feedback, running summary, conversation history), each tagged with a **priority number**, then `_fit_budget` greedily includes the highest-priority sections that fit within `max_context_tokens`. Artifacts can be partially trimmed to fit (`_trim_section_to_token_budget`). This is a **priority-ordered token budget** — the single most important technique for keeping prompts bounded regardless of how much evidence has accumulated.

### 5.3 Truncation and structured facts — `context/truncator.py`

`truncate_tool_result` produces two views of every tool result: a human/LLM-readable `summary` (bounded by `max_artifact_chars`) and a compact `raw_ref` structured reference. Strings, dicts, and lists each have tailored handling (`_truncate_dict`, `_truncate_list`, `_fit_dict_list_items`). `_compact_raw_ref` normally reduces big collections to counts and keys, but `_preserve_structured_fields` keeps a **bounded copy** of recognized structured fields (`facts`, `items`, `rows`, `panels`, `tables`, and nested `data.facts` / `display.tables`) so the fact extractor can use them. `_fit_structured_value` enforces the size bound and, critically, drops a single oversized item rather than exceeding budget. `extract_source_ref` pulls citation metadata; `make_artifact_id` fingerprints content for stable ids.

### 5.4 Scoring — `context/scorer.py`

`score_artifact` ranks each artifact on four factors — **relevance** (query-term overlap or a semantic score), **freshness** (exponential decay by age with a configurable half-life), **uniqueness** (low overlap with existing artifacts), and **actionability** (presence of ids, rows, names) — combined by configurable weights into a `composite` score. This composite drives artifact retention, context ordering, and which artifacts the summarizer folds first. `content_fingerprint` provides stable hashing.

### 5.5 Tool provider and MCP — `providers/`

`ToolProvider` and `LlmProvider` are `Protocol`s, so any conforming implementation can be injected (this is what makes the whole engine testable with mocks). The production tool provider is `RemoteMcpToolProvider` (`providers/mcp.py`), built by `create_tool_provider`; multiple servers are wrapped by `MultiMcpToolProvider`, and no configuration yields `EmptyToolProvider`.

Tool discovery is two-tier: a **semantic search** tool on the MCP server (`SEMANTIC_SEARCH_TOOL`) or a dedicated tool-index endpoint (`HttpToolIndexProvider`) when configured, otherwise a **local token-overlap ranking** over a cached catalog (`_rank_catalog`). The catalog is cached with a TTL to avoid re-listing tools every turn. `normalize_mcp_tool_result` flattens the various MCP response shapes into plain data, and `_validate_arguments` guards calls. The LLM provider is `OpenAiChatCompletionsProvider` (OpenAI-compatible chat completions, with optional native tool calling and token-usage accounting).

### 5.6 Configuration — `config.py` and `runtime_schema.py`

Configuration is a two-layer system. `runtime_schema.py` holds **pydantic validation models** (`AgentConfigModel` and friends) with `extra="forbid"` and per-field bounds — this is the strict gate that rejects unknown keys and out-of-range values. `config.py` holds the **runtime dataclasses** (`AgentConfig`, `AgentPolicy`, and the sub-policies `TruncationPolicy`, `ToolPolicy`, `PlannerDefaults`, `ReviewerDefaults`, `ExecutorDefaults`, `FinalizerDefaults`, `SummaryDefaults`, `RouterDefaults`, `ContextLimits`).

`parse_agent_config` validates raw input, resolves `${ENV_VAR}` placeholders, and coerces values into the dataclasses. `load_agent_config` reads a YAML/JSON file. `merge_agent_config` applies runtime overrides onto a base config (used by the runtime-bundle API). `AgentConfig.signature` produces a **stable, secret-free hash** of the whole config that keys the graph/provider caches. `AgentConfig.prompt_text` resolves a role's system prompt (inline text or a prompt file).

A notable design detail: nested toggles like `planner.enabled` and `reviewer.max_cycles` default to `None` in the schema so that flat aliases (`enable_planner`, `max_review_cycles`) are honored with clear precedence — nested wins only when explicitly set.

### 5.7 Deadlines — `deadlines.py`

Every LLM and tool call is wrapped in `run_with_deadline`, which runs the operation on a shared thread pool and raises `DeadlineExceeded` if it overruns `llm_timeout_seconds` / `tool_timeout_seconds`. Context variables are propagated into the worker so tracing still works. Every node catches this and degrades gracefully (a timeout answer, a fallback memo, a best-effort draft) rather than hanging the request.

### 5.8 Caching — `cache.py`

`get_or_create_graph` and `get_or_create_provider` are thread-safe **LRU caches** keyed by config signature (plus provider identity for the graph). This is the "compile-once" optimization: repeated API calls with the same config reuse the same compiled graph and the same LLM/MCP providers, so there is no per-request build cost. `clear_engine_caches` resets them (used between tests).

### 5.9 Checkpointing — `checkpointing.py` and durable approval

The graph is compiled with a checkpointer. The default is an in-process `MemorySaver`; a durable backend (e.g. Redis/Postgres) can be declared in `resources.checkpointer` for multi-worker deployments. Checkpointing is what makes the approval interrupt durable — a paused run can be resumed later, even by a different worker, with `Command(resume=...)`. `delete_thread` cleans up terminal threads.

### 5.10 Cross-turn artifact persistence — `artifact_store.py`

When enabled (`cross_turn_artifact_persistence`), `CrossTurnArtifactStore` saves a session's top-scoring artifacts to Redis with a TTL. On the next turn in the same session, `_prepare_session` loads them so a follow-up can reuse prior evidence instead of re-running tools. This is session-scoped episodic memory, keyed by `session_id`.

### 5.11 Telemetry — `telemetry.py`

`begin_turn_trace` / `finish_turn_trace` bracket a turn; `llm_call` is a context manager that records each model call and token usage; `record_workflow_update` snapshots node updates. `trace_event_messages` renders a compact debug trace attached to responses when `AGENT_WORKFLOW_DEBUG_TRACE` is on. Token-usage deltas are attached to every result as a `telemetry.llm_usage` event.

### 5.12 The HTTP layer — `api/`

`api/routes.py` exposes the endpoints under `/api/agent-workflow`. `api/runtime.py` resolves the right engine for a request (by config name/path/inline config/runtime bundle) and drives streaming. `api/sse_adapter.py` (`engine_event_to_sse`, `_ACTIVITY_FIELDS`, `sse_encode`) converts internal events into Server-Sent Events, keeping only whitelisted fields. `RunRequestModel` and the request schemas validate all input.

---

## 6. Feature deep-dives (the notable capabilities)

### 6.1 Follow-up query rewrite

On a follow-up turn a bare question ("how many are there?") has no nouns for semantic tool search. The planner is asked to emit a `### Search Query` section — a standalone, pronoun-resolved query — parsed into `plan.search_query` and surfaced as `state["search_query"]`. The executor derives its retrieval query from `search_query` instead of the raw `user_query`, so semantic search matches on real nouns.

The rewrite lives in the **planner** because the planner already runs once and already sees history, so it costs zero extra LLM calls. `build_search_query` (`follow_up.py`) is the deterministic fallback (prepend the last user turn on follow-ups) used when the planner is disabled; it is seeded in `_initial_state` so it is always present. The literal `user_query` is never overwritten, so the final answer still addresses what was actually asked.

### 6.2 In-loop running summarizer (memory compaction)

As the executor loops, evidence accumulates. Rather than blindly dropping low-score artifacts (losing their information) or letting context grow unbounded, the summarizer **compresses before it drops**. `_should_compact` triggers the detour when retained artifacts reach `summary.compact_after_artifacts` and the cycle cap isn't hit. `summarizer_node` folds the lower-scoring artifacts into `running_summary`, keeps the top `summary.keep_after_summary` verbatim, and returns to the executor with freed context. The memo is injected high-priority into the executor prompt and seeded into facts, so nothing is silently lost. It is opt-in (`enable_running_summary`, on in `default.yaml`) and bounded three ways: the cycle cap, a keep-count clamped below the trigger so compaction always clears, and a deterministic fallback on timeout.

### 6.3 Robust reviewer parsing

Models return verdicts as JSON, as markdown, or as prose. `_parse_review` tries JSON first (`_try_json_object` + `_has_review_signal`), then markdown (`parse_review_markdown`), then falls back to a safe `REVISE` and emits `reviewer.parse_failed`. This prevents both silent mis-parses (which previously forced needless revision cycles) and mistaking an executor action payload for a verdict.

### 6.4 The structured fact contract

Tools can return rich structure. The fact extractor looks for structured facts at known locations (`facts`, `data.facts`, `display.facts`, `metadata.facts`) and generic collections (`items`, `results`, `rows`, `panels`, `display.tables`) via `_structured_entries` over `_FACT_PATHS` / `_COLLECTION_PATHS`, and only falls back to line-splitting summaries when no structure exists. For this to work end-to-end, `truncate_tool_result` **preserves** those bounded structured fields in `raw_ref` (they would otherwise be reduced to counts). This is app-agnostic: any MCP tool that returns `{facts: [...]}` or `{panels: [...]}` gets richer extraction for free, and the recommended way to make large collections fully extractable is to return them under these keys rather than as a bare top-level list.

### 6.5 Execution memory that survives compaction

Because the summarizer drops artifacts, the executor cannot rely on artifacts alone to remember which tools already ran. `_called_tools_for_step` therefore reads **both** artifacts and `tool_calls` (the latter now carry `step_index`/`replan_id` and are not dropped by the summarizer). This keeps duplicate-tool prevention and required-tool checks correct even after aggressive compaction.

### 6.6 Provenance sidecar

Citations must survive compaction too. The summarizer preserves each folded artifact's provenance (`id`, `tool`, `source_ref`) in a structured `summary_sources` list — independent of the prose memo, so it can't be mangled by the model. Two mechanisms then complement each other: the memo text carries inline source markers keyed by artifact id (best-effort, for the model to cite in prose), and the sidecar gives the finalizer structured refs (guaranteed, consumed by `_grounding_source_refs` when grounding is enforced).

### 6.7 Exactly-once terminal event

Several nodes set `phase: "done"` as a routing signal, but only the finalizer should emit the terminal `done`. `map_graph_update` takes the node name and emits `done` only for the finalizer's update, so hosts and callbacks never see duplicate or premature terminal events.

---

## 7. Follow-up handling — `follow_up.py`

Beyond query rewrite, this module decides how a follow-up turn should behave. `is_follow_up_query` detects references to prior output. `resolve_follow_up_policy` decides whether the turn can reuse persisted artifacts or must re-run tools; `apply_follow_up_runtime_context` records that decision for downstream nodes. `infer_evidence_tools` maps intent keywords to the tools that should be re-run. `follow_up_tool_recall_missing` and `follow_up_approval_gaps` feed the reviewer's deterministic completion checks, so an answer that skips required fresh evidence on a follow-up is caught.

---

## 8. Optimizations catalog

The service is tuned for **cost and stability**, not just raw speed. The main levers:

- **Fast-path router** (`_can_fast_path`). Trivial queries (greetings, arithmetic, short ungrounded questions) skip the entire graph and answer with one LLM call. Governed by the `router` policy and intent regexes; anything with tool/complex intent or conversational context is refused the fast path.
- **Compile-once graph + provider caching** (`cache.py`). No per-request build cost.
- **Priority-ordered token budgeting** (`ContextBuilder._fit_budget`). Prompts stay within `max_context_tokens` no matter how much evidence exists.
- **Deterministic fact extraction.** Compression from artifacts to facts costs no LLM call.
- **Single authoring pass.** One synthesis call is the norm; the reviewer and revision only run when warranted.
- **Risk-gated reviewer** (`_run_has_risk`, reviewer `mode: on_risk`). Clean tool runs skip the reviewer LLM call entirely; failures or errors trigger it.
- **Conditional finalizer render.** LLM prose drafts are reused, not re-rendered.
- **Native tool calling with prefetch.** Saves the separate search round-trip when the model supports it.
- **Tool discovery cache + catalog TTL.** Repeated searches and tool listings are free within a turn / TTL window.
- **Bounded loops everywhere.** Executor iterations, review cycles, revision cycles, and summarizer cycles are all capped; the graph physically cannot spiral.
- **In-loop memory compaction.** Trades one summarizer call for freed context so long investigations stay within budget instead of dropping evidence.
- **Cross-turn artifact reuse.** Follow-ups can skip re-running tools by loading persisted evidence.

---

## 9. How to use it

### 9.1 Configure an agent

An agent is a YAML file (see `agents/default.yaml`) with three main sections:

- **`llm`** — base URL, model, sampling parameters, and `native_tool_calling`. Values can reference environment variables with `${VAR}`.
- **`mcp`** — the tool server(s): a single `url` or a list of `servers`, each optionally with its own semantic tool-discovery endpoint.
- **`policy`** — everything else: loop caps, timeouts, retention limits, the feature toggles (`enable_planner`, `enable_reviewer`, `enable_fast_path`, `enable_running_summary`, `cross_turn_artifact_persistence`, `enforce_grounding`), and the sub-policy blocks (`truncation`, `executor`, `finalizer`, `summary`, `reviewer`, `planner`, `router`, `context`, `tools`).

Prompts for planner, executor, and reviewer live in `prompts/` and are referenced by path (or inlined via `prompts_inline`). Because the schema is strict (`extra="forbid"`), a typo in a key is a validation error, not a silent no-op.

To tune for a workload: raise `truncation.max_artifact_chars` for dashboard/report agents that return large structured payloads; raise `max_list_rows_visible` for high-volume tables; keep budgets modest for quick chat tools. To disable a stage, set its enable flag to false (disable review via `enable_reviewer: false`, not `reviewer.max_cycles: 0`).

### 9.2 Call it over HTTP

Endpoints live under `/api/agent-workflow` (`api/routes.py`), guarded by an API key dependency:

- **`POST /run`** — run to completion, returns the answer plus review, counts, events, and (optionally) a debug trace.
- **`POST /stream`** — the same run as Server-Sent Events: `status`, `plan`, `agent_activity`, `review`, `delta` (answer tokens), and a final `done`.
- **`POST /resume`** — continue a run that paused for destructive approval, with `approved: true|false`.
- **`POST /run/runtime-bundle`** and **`/stream/runtime-bundle`** — the same, but the caller supplies a base config plus runtime overrides that are merged (`merge_agent_config`) before the engine is resolved.

Each request identifies the agent by config name, config path, inline config, or runtime bundle; the engine is resolved and cached per config signature.

### 9.3 Use it as a library

Construct an engine with one of the class methods on `AgentEngine`: `from_config` (from a file), `from_dict` (from a parsed config), or `from_runtime_config` (base plus overrides). Each accepts optional `llm`, `tools`, `callbacks`, and `checkpointer` for injection — passing mock providers is exactly how the test suite drives the engine deterministically.

Then call `run(RunRequest(query=..., session_id=..., history=..., runtime_context=...))` for a synchronous `RunResult`, or iterate `stream(...)` for events. Provide `HostCallbacks` (`on_plan`, `on_tool_call`, `on_artifact`, `on_review`, `on_event`, `on_destructive_action`) to observe or gate activity. For destructive tools, either supply a synchronous `on_destructive_action` approver or handle the paused run and call `resume(thread_id, approved=...)`.

### 9.4 The approval flow in practice

If a run calls a tool listed in `destructive_tools` and no synchronous approver approves it, the run pauses: `run` returns a `RunResult` with `pending_approval` set (and `stream` yields a `pending_approval` event). The state is checkpointed under the `thread_id`. The host presents the pending action to a human, then calls `resume(thread_id, approved=True)` to execute it or `approved=False` to skip it; the workflow finishes from where it paused.

---

## 10. Concepts and techniques glossary

- **LangGraph state machine.** The workflow is a graph of nodes over a shared `AgentState`; routing is data-driven off `phase`.
- **Separation of concerns.** Each node owns one phase; the executor gathers, the synthesizer writes, the reviewer judges, the reviser rewrites, the finalizer renders.
- **Bounded loops.** Every loop has an explicit counter and cap, so termination is guaranteed.
- **Progressive compression.** Raw tool output → truncated artifact → scored/retained artifact → (compacted running summary) → compact fact → answer. The model sees less and less raw data as it moves toward writing.
- **Priority token budgeting.** Context is assembled by priority and clipped to a token budget rather than by fixed slots.
- **Provenance preservation.** Source refs are carried structurally (in `raw_ref`, in facts, in `summary_sources`) so citations survive truncation and compaction.
- **Graceful degradation.** Deadlines plus per-node fallbacks mean a slow model or tool yields a best-effort answer, never a hang.
- **Compile-once / cache-everything.** Graphs, providers, tool catalogs, and discovery results are cached and reused.
- **Human-in-the-loop via checkpointed interrupts.** Destructive actions pause durably and resume on approval.
- **Strict, layered configuration.** A validating schema over runtime dataclasses, keyed by a secret-free signature.
- **Provider protocols.** LLM and tool access are interfaces, making the engine injectable and testable.

---

*This document describes the working architecture of the service as implemented under `app/agent_workflow` and `app/api`. Names in monospace refer directly to the functions, classes, and config keys in those modules.*
