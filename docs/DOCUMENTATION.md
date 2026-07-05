# Agent Workflow Service — Complete Documentation

*A verbal tour of the project: what it is, how it thinks, what it can do, and how to plug it into your own applications.*

---

## 1. What It Is

The Agent Workflow Service is a standalone, self-contained runtime for running AI agents. You hand it a question and a configuration, and it plans, uses tools, checks its own work, and returns a grounded, polished answer — either all at once or as a live stream of progress events.

It is two things in one codebase:

- **An HTTP service.** A small FastAPI application that listens on its own port, accepts run requests, streams progress over Server-Sent Events, and pauses for human approval when an agent wants to do something destructive.
- **A reusable Python library.** Everything the HTTP layer does, an embedding application can do directly by constructing an engine and calling it. The HTTP layer is just one thin adapter over the same core.

The core belief behind the design: **an agent is configuration, not code.** A new agent for a new application should require a new configuration file, new prompts, and a set of tools — never a change to the framework itself. The framework has no knowledge of notes, documents, or any particular product; every application-specific idea lives in the configuration.

---

## 2. The Design Philosophy

Five principles shape almost every decision in the codebase:

**Fail closed.** When the agent wants to do something dangerous and nobody is present to approve it, the run pauses. It never guesses that permission was probably fine. The same instinct applies to the API: if no access key is configured, the service refuses requests rather than quietly serving everyone.

**Stay grounded.** The agent's answers should come from evidence — the results of the tools it called — not from the model's imagination. Every part of the pipeline, from the router that decides whether a question is trivial, to the context packer that decides what the model sees, to the final answer renderer, is biased toward keeping tool evidence in front of the model.

**Bound everything.** Loops have turn limits. Reviews have cycle limits. Tool calls per step are capped. The context is packed into a token budget. Every model and tool call runs under a deadline. Memory held per run is pruned to fixed sizes. There is no code path that can grow or spin forever.

**Degrade gracefully.** When something fails — a timeout, a rejected plan, a tool error, a recursion limit — the run does not simply crash. It falls back to the best answer it can assemble from the evidence it already gathered, and it says so honestly in its events.

**Compile once, reuse everywhere.** Building an agent graph is expensive; running one is not. Graphs, providers, and connections are built a single time per unique configuration and cached, so serving traffic is cheap and predictable.

---

## 3. The Cast of Characters

An agent run is a small team of specialists passing work between each other. Each one is a node in a graph, and the graph decides who speaks next.

**The Router** sits at the front door. Before any heavy machinery starts, it looks at the question and asks: is this trivial? A greeting, a thank-you, a bit of arithmetic? If so, it answers directly with a single model call and the run is over. The router is deliberately conservative — a short question that *might* need tools always takes the full path, because the worst failure mode of a retrieval product is a confident answer invented from thin air. Callers can force the full path, and can explicitly permit ungrounded quick answers if they want them.

**The Planner** turns the user's request into a short, numbered plan: a goal, assumptions, risks, concrete steps with tool hints, and acceptance criteria. For simple agents, the planner can be switched off entirely in configuration, in which case the request becomes a single implicit step and execution begins immediately.

**The Executor** is the workhorse. It works through the plan one step at a time. On each turn it looks at everything it knows — the plan, the evidence gathered so far, recent tool activity, reviewer feedback — and chooses exactly one action: search for tools, call a tool, finish the current step, or draft the answer. Every tool call is policy-checked, schema-validated, argument-injected, and executed under a deadline. Results are scored, summarized, and stored as *artifacts* — the evidence the rest of the pipeline runs on.

**The Approval Gate** wakes up only when the executor wants to run a tool that the configuration lists as destructive. If the host application registered a synchronous approver, it is asked on the spot. If not, the run checkpoints itself and pauses; the caller receives a pending-approval notice with a thread identifier, and the run stays frozen — across process restarts and across different workers, if a durable checkpoint store is configured — until someone resumes it with an explicit approve or deny. A denied tool is remembered and never silently retried.

**The Reviewer** reads the draft answer against the plan's acceptance criteria and the gathered evidence, and returns a verdict: approve, revise, or reject. A revision sends the executor back to work with concrete feedback. A rejection can trigger a full replan. Both loops are cycle-limited, and when the limit is reached the run ends honestly with the best available answer and an explanatory error. The reviewer can also run in an economical mode where it only engages when something actually went wrong during the run — a failed tool call, a denial, an error — and clean runs skip the review entirely.

**The Finalizer** is the last voice before the answer leaves the building. If the draft is a mechanical evidence dump, the finalizer rewrites it into natural prose, streaming the words token by token as it goes. If the draft is already well-written prose — because the model or the reviewer wrote it — the finalizer wisely does nothing and passes it through, saving a whole model call. Because the finalizer is a real graph node, its output is checkpointed: the answer a resumed or replayed run sees is exactly the answer the user saw. An optional grounding enforcement appends source references when the answer forgot to cite its evidence.

---

## 4. The Life of a Request

Imagine a request arriving: *"Find every mention of the payment SLA in our vendor contracts and summarize the obligations."*

First, authentication. The request must carry the service's access key; without it, nothing else happens.

Second, resolution. The service figures out which agent should handle this — a named configuration from its allowlisted directory, an inline configuration in the request body, or a runtime bundle from an orchestrating platform. Whatever the source, the configuration is validated against a strict schema, any environment placeholders are resolved, and any outbound addresses it names — the model endpoint, tool servers, checkpoint stores — are checked against an allowlist of permitted hosts.

Third, the router glance. This question mentions contracts and searching, so it is clearly not trivial; the full graph engages. A fresh thread identifier is minted for this run, unique even if the same conversation has run before.

Fourth, planning. The planner produces perhaps three steps: search the contract collection, extract SLA clauses, compose a summary of obligations.

Fifth, execution. The executor takes the first step. It discovers candidate tools — possibly by asking a semantic tool index which tools best match "search vendor contracts", possibly from the tool catalogs of its configured servers. It picks one, fills in the arguments, and before anything runs, the framework validates those arguments against the tool's schema and injects any values the configuration says must come from trusted runtime context — a tenant identifier, a user identifier — regardless of what the model wrote. The tool runs under a deadline. Its result is compressed into a scored artifact: a compact summary the model can read, a small structural fingerprint of the raw result, and a source reference for citation. The executor continues, step by step, turn by turn, all of it bounded.

Sixth, drafting and review. When the steps are done, a draft answer is assembled — preferentially a deterministic digest of the artifacts, so nothing is invented. The reviewer weighs it against the acceptance criteria. Perhaps it demands one revision; the executor obliges.

Seventh, finishing. The finalizer renders the approved draft into flowing prose, streaming each token to the caller as it is generated. The done event follows, carrying the final answer, the review verdict, artifact and tool-call counts, and the run's token usage. The run's checkpoints are deleted — the thread is finished, and nothing about it lingers in memory.

If, at step five, the executor had chosen a tool marked destructive — say, deleting a contract — the story would have paused at the approval gate instead, and the caller would hold a thread identifier with which to resume it later, on any worker.

---

## 5. Tools and the MCP World

The service does not define tools itself. Tools live in external MCP servers — independent services that speak the Model Context Protocol — and the framework connects to as many of them as the configuration lists.

**Discovery is dynamic.** At runtime, the framework asks each server for its tool catalog, following pagination, and caches the merged catalog briefly so repeated runs do not hammer the servers. When two servers offer tools with the same name, the duplicates are disambiguated with a server prefix so there is never ambiguity about which one runs.

**Discovery can be semantic.** Instead of scanning catalogs, the framework can query a vector-backed tool index — give it a sentence about what the step needs, and it returns the best-matching tools with scores. The index endpoint can be configured per server, or once for the whole agent through the shared resources section, and the catalog scan remains as a fallback.

**Selection is governed by policy.** The configuration can allowlist tools, denylist tools, require specific tools for specific plan steps (the run will not consider a step finished until they have run), and declare argument injection — a mapping that says certain tool arguments always come from the trusted runtime context, never from the model. This last one is the quiet security cornerstone: even a fully confused or manipulated model cannot aim a tool at another tenant's data, because the tenant argument is stamped in by the framework.

**Execution is defensive.** Arguments are validated against the tool's JSON schema before the call. Results are normalized — MCP's structured content is preferred, text payloads are parsed when possible — and immediately compressed by the truncator so that huge tool outputs never bloat the run's memory. Transient server errors and rate limits are retried with backoff, honoring the server's retry-after guidance.

**Native tool calling.** For models that support the OpenAI tools contract, the configuration can switch the executor into native mode. The framework then discovers candidate tools deterministically from the step text — spending no model call on discovery — and offers them to the model as real, first-class tool definitions. The model either calls one natively or says in plain terms that the step is done. Every guardrail — policy, schema validation, injection, the destructive gate — applies identically. If the model server rejects the native contract, the executor notices and falls back to its classic mode within the same turn, so enabling the feature is safe everywhere.

---

## 6. Memory, Context, and Compaction

A long agent run generates far more information than a model context can hold, and far more than a process should keep in memory. The framework manages both pressures deliberately.

**Artifacts are the unit of memory.** Every tool result becomes an artifact with four scores — relevance to the step, freshness, uniqueness against existing artifacts, and actionability — blended into a composite. When the retained set exceeds its configured cap, the lowest-scoring artifacts are dropped first. Tool-call records and event logs have their own independent caps.

**Raw results stay out of state.** The truncator keeps a readable summary and a compact structural reference — counts, key names, identifiers, a truncation flag — instead of the raw payload. The reference is enough for a host application to re-fetch or audit the original if it needs to; the run itself never carries the weight.

**The context is packed, not dumped.** Before every model call, a context builder assembles labeled sections — the user request, the plan with the current step highlighted, candidate tools, artifacts sorted by score, recent tool calls, reviewer feedback, conversation history — each with a priority. Sections are admitted in priority order under a strict token budget. The artifacts section, uniquely, is trimmed from the bottom rather than dropped whole when it does not fit, because losing the grounding entirely is the one failure the packer must never allow.

**Discovery results are cached inside the run.** Repeated tool searches for the same need hit an in-state cache instead of the network, and a loop breaker notices when the model keeps searching despite already having candidates, forcing progress instead of a spin.

---

## 7. Resilience: How It Survives a Bad Day

**Typed errors drive retries.** Failures from the model server and tool servers are classified. Server-side errors and rate limits are transient: they are retried up to three times with exponential backoff, and when the server names a retry-after delay, that delay is respected. Client-side errors are permanent: they fail immediately, because retrying a bad request only wastes time. Streaming responses get the same classification, and a stream that fails before its first token is retried; one that fails mid-answer is not, so callers never receive duplicated text.

**Deadlines wrap every external call.** Each model and tool call runs inside a shared worker pool with a time budget. The transport timeout is kept slightly inside the deadline so the network layer unwinds itself before the deadline fires — the deadline is a safety net, not the primary mechanism — and request-scoped logging context follows the work into the pool so log lines stay correlated.

**Connections are pooled.** The model provider and each tool server hold one persistent HTTP client each, reused across all calls, and every cached component is properly closed when it is evicted or when the service shuts down.

**Failure has a floor.** Whatever goes wrong — timeout, rejection, recursion limit, provider outage — the run ends with the best grounded answer assemblable from the artifacts already gathered, an honest error field, and clean resource state.

---

## 8. Checkpointing, Resume, and Shared Resources

Every run writes its progress into a checkpoint store under its thread identifier. This is what makes the pause-and-resume approval flow real rather than cosmetic.

The store is pluggable. By default it is in-process memory, suitable for development. For production, an environment setting or — more elegantly — the configuration's **resources** section selects a Redis or PostgreSQL store. Resources declared in configuration resolve through a shared registry, so every engine pointing at the same backend shares one connection, and a run paused on one worker can be resumed by any other worker behind the same load balancer. Completed runs delete their threads immediately; a client that disconnects mid-run also triggers cleanup, while a run paused for approval is carefully preserved.

The same resources section carries the default semantic tool index address, applied to every tool server that does not name its own. The intent is a single place where an operator declares shared infrastructure — checkpoint store, vector index — and the runtime picks each one up wherever it is needed.

---

## 9. Configuration: The Product Surface

A configuration file describes an agent completely. In words, it contains:

- **An identity** — the agent's name.
- **Prompts** — the planner, executor, and reviewer instructions, either as paths to prompt files or inline text. Prompt text may reference environment variables, which are resolved at load time.
- **A model section** — the OpenAI-compatible endpoint, model name, sampling parameters, an optional key, and the switch for native tool calling.
- **A tools section** — one or more MCP servers, each with its address, optional token, timeout, and optional semantic discovery settings.
- **A policy section** — every knob that shapes behavior: iteration and review-cycle limits, per-step tool caps, the context token budget, model and tool deadlines, retention caps for artifacts and history, the list of destructive tools, whether the fast path is allowed, whether the final answer is rendered, whether grounding is enforced, whether the planner runs at all, the reviewer's mode (always, or only on risk), tool allow/deny/required lists, and argument injection mappings.
- **A resources section** — the shared checkpoint store and tool index described above.

Three delivery mechanisms exist. A configuration can be a **named file** in the service's allowlisted directory. It can be sent **inline** in a request body, optionally combined with **runtime overrides** that deep-merge onto a base — how a hosting platform customizes one agent per tenant without new files. Or it can arrive as a **runtime bundle**, an externally assembled package of prompts, model settings, and connector definitions that an adapter translates into a standard configuration.

Every parsed configuration produces a **signature** — a cryptographic digest of its full contents, with secrets hashed rather than embedded. The signature is the key for every cache in the system, which means two tenants with different credentials can never share a graph or a connection, while identical configurations share everything.

---

## 10. The HTTP Surface

The service exposes a handful of endpoints under one prefix, all guarded by the same key check.

- A **health** endpoint answers liveness probes.
- A **run** endpoint executes synchronously and returns the final answer, the review verdict, counts of artifacts and tool calls, any pending approval, and the thread identifier in one JSON envelope.
- A **stream** endpoint delivers the same run as Server-Sent Events: a metadata event first, then status updates, the plan, tool activity as it happens, review results, the answer as a stream of text deltas, and a final done event with the complete answer and token usage.
- Bundle variants of both accept a runtime bundle instead of a configuration reference.
- A **resume** endpoint takes a thread identifier and an approve-or-deny decision, and continues a paused run to completion.

The security posture, in one breath: requests without the configured key are refused (and if no key is configured, everything is refused); configuration files can only be read from one allowlisted directory, by name, with path escapes rejected; every outbound host a request names — model endpoint, tool servers, tool index, checkpoint store — must appear on the operator's allowlist, which defaults to localhost only; runtime context sent by callers is depth-checked, size-checked, and scrubbed of prototype-pollution keys; and the API key comparison is constant-time.

---

## 11. Observability

Every run narrates itself. Nodes emit structured events for each decision: what action the executor chose, which tools were searched and found, each tool call with its arguments preview, status, and latency, each review verdict with its issues and required changes, every fallback and loop-breaker intervention. These events flow to streaming clients in real time, are returned with synchronous results, and are capped in retained size so they can never bloat a run.

Token accounting is built in: the model provider records prompt and completion tokens from both regular and streaming calls, and every run reports the usage it consumed — the raw material for cost attribution and latency budgets. Logging context propagates across the internal worker pool, so a log line written deep inside a tool call still carries its request's identity.

What is deliberately not built in yet: an OpenTelemetry exporter and a metrics backend. The events and usage data are all present; shipping them to a specific observability stack is left to the operator or a future adapter.

---

## 12. Performance Features

The cost model of an agent is the number of sequential model calls per run, and the framework attacks it from several angles:

- The **fast path** answers trivial messages with one model call and no graph at all.
- The **planner can be disabled** per agent, removing a call for single-step use cases.
- **Native tool calling with deterministic pre-discovery** removes the model call previously spent deciding to search for tools.
- The **conditional finalizer** skips the final rendering call whenever the draft is already prose.
- The **risk-gated reviewer** skips the review call for runs where nothing went wrong.
- **Compile-once graphs, cached providers, pooled connections, and short-lived discovery caches** keep the per-request overhead close to zero beyond the model calls themselves.

With everything enabled, a clean trivial message costs one model call; a clean single-step tool run costs roughly three (one tool-selection turn, one finish turn, one render — or two, when the draft needs no render); and each additional plan step adds roughly one to two calls.

---

## 13. Integrating It

**As a service**, integration is three steps. Deploy it next to your model server and MCP servers, with the environment describing the model endpoint, the API key, the allowed outbound hosts, and — for production — a Redis or PostgreSQL checkpoint store. Write one configuration file per agent and mount it into the allowlisted directory. Then call the run or stream endpoint from your backend with the user's message, conversation history, and a runtime context carrying trusted identifiers; map the SSE events onto your product's progress UI; and wire an approval button to the resume endpoint. The event vocabulary was designed to map directly onto a chat interface: status lines, a plan card, tool activity chips, review summaries, streaming text, and a final done.

**As a library**, an embedding application builds an engine from a configuration and calls its run, stream, or resume methods directly, receiving the same events as Python dictionaries. Host callbacks allow the application to observe plans, tool calls, artifacts, and reviews inline, and to supply a synchronous destructive-action approver so approvals resolve without pausing. Custom model or tool providers can be injected outright — anything satisfying the small provider protocols works, which is also how the test suite runs the entire framework against scripted fakes.

**For a brand-new application**, the checklist is: stand up or reuse MCP servers exposing your domain's tools; write prompts that speak your domain's language; write one configuration naming the model, the servers, the destructive tools, the policies, and the budgets; and decide the checkpoint store. No framework code changes — that is the adapterization promise, and the codebase holds it.

---

## 14. How to Best Use This Agent Workflow

The framework has many switches, and the difference between a mediocre agent and an excellent one is mostly how thoughtfully they are set. This section is the accumulated advice — how to shape an agent for its job, how to tune it, and how to run it well.

### Match the agent's shape to the job

Not every task deserves the full machinery, and the configuration lets you shrink the pipeline to fit.

For a **simple conversational assistant** whose questions rarely need tools, leave the fast path on and keep a single, small tool server. Most messages will resolve in one model call; the rare tool-worthy question still gets the full treatment.

For a **retrieval assistant** — the classic "answer from my documents" product — turn the planner off. The request becomes one implicit step, the executor searches and reads, and the answer arrives two or three model calls sooner. The planner earns its keep only when requests genuinely decompose into stages.

For a **research or analysis agent** that must gather from several sources, compare, and compose, keep the planner on and give the reviewer real acceptance criteria to check against. This is the shape the plan-execute-review loop was built for, and it is where the reviewer's revise-and-replan cycles visibly improve answers.

For an **operations agent** that changes things — deletes, sends, deploys — the destructive tools list is not optional. Name every mutating tool in it, decide who approves (a synchronous callback for interactive hosts, the pause-and-resume flow for everything else), and use a durable checkpoint store so a pending approval survives anything short of losing the database.

### Start safe, then economize

The cost-saving features are opt-in for a reason: the right order is to make the agent *good*, then make it *cheap*.

Begin with the reviewer always on and final-answer rendering always on. Run real traffic. Read the review verdicts in the events — if the reviewer approves nearly everything on the first pass, switch it to its risk-gated mode and reclaim that model call on clean runs; the reviewer still engages the moment a tool fails. The conditional finalizer needs no decision at all — it automatically skips re-rendering when the draft is already prose.

If your model server supports the OpenAI tools contract, enable native tool calling. It removes a model call per step, and because the executor falls back to the classic mode automatically if the server rejects the contract, turning it on is risk-free. Watch the events for fallback notices to learn whether your server actually honors it.

### Write prompts that respect the machinery

The prompts are where your domain enters the system, and the machinery has expectations. The executor prompt should insist on using the evidence artifacts and never inventing facts — the framework keeps evidence in front of the model, but the prompt sets the intent. The planner prompt should push toward few, concrete, tool-shaped steps; vague plans produce wandering executions that burn turns. The reviewer prompt should judge against the plan's acceptance criteria rather than general quality, because that is exactly what the reviewer node feeds it. Keep all three in your domain's vocabulary; the framework's own instructions handle the mechanics.

### Use the policy section as your safety contract

Argument injection is the single most important line of defense in a multi-tenant product: declare that every tenant-scoped tool argument comes from the trusted runtime context, and the model becomes incapable of reaching across tenants no matter what it is told. Denylist tools the agent should never see; allowlist when the catalog is large and the agent's scope is narrow; use required tools when a step is meaningless without a particular call — the run will refuse to consider the step finished until it happens.

### Tune the budgets to your infrastructure

Set the context token budget comfortably inside your model's window, leaving room for the system prompt and the model's own output. Set model and tool deadlines from your servers' real latency distributions — a deadline tighter than your slowest healthy call converts ordinary slowness into failures, while an overly generous one lets a sick backend hold worker threads hostage. The retention caps rarely need touching; raise the artifact cap only for genuinely long investigations, and remember everything retained is re-packed into every subsequent model call.

### Discipline the runtime context

The runtime context is the trusted channel between your backend and the run. Put identity there — user, tenant, workspace — because injection depends on it. Use the force-agent flag when your product knows a message needs tools regardless of how trivial it looks, and grant the allow-ungrounded flag only where a fast parametric answer is genuinely acceptable. Never put anything in runtime context that came unfiltered from an end user, because the whole point of the channel is that the framework trusts it.

### Operate by the events

The event stream is not just UI decoration; it is the operational truth. Log the done events with their usage figures for cost attribution. Watch the distribution of router decisions to see how much traffic the fast path absorbs. Watch review verdicts to know whether your prompts and the reviewer agree. Watch tool-call failure events and native-fallback notices to catch infrastructure drift early. When something behaves oddly, the per-run event trail usually explains it without any debugger.

### Size it honestly

Each active run occupies a worker thread for its full duration, so a single instance is comfortable at tens of concurrent runs, not hundreds. Scale horizontally: instances are stateless once the checkpoint store is durable and shared, so any number of replicas can sit behind one load balancer, and approvals resume wherever they land.

---

## 15. What Else Can This Agent Workflow Do?

The service was born inside a note-taking product, but nothing in it knows about notes. Its real identity is a general, governed tool-using loop — and that shape fits many more jobs than a chat box.

**Batch and offline work.** The synchronous endpoint makes the agent a callable function: no streaming, no user watching. A nightly job can ask it to compile a digest of the week's changes, reconcile two systems and summarize the differences, or generate a report per customer — each run bounded, grounded, and returning token usage for cost tracking. The same determinism that makes it testable makes it schedulable.

**Automation with human sign-off.** The pause-and-resume approval flow is a general pattern, not a chat feature. An agent can triage a queue — closing stale tickets, archiving old records, revoking unused access — executing the safe actions immediately and pausing on each destructive one. The pending approval, durable in the checkpoint store, becomes an item in a human review queue; approving it resumes the run on whatever worker picks it up. That is a human-in-the-loop automation platform in miniature.

**One agent across many systems.** Because an agent may list several MCP servers at once — with name collisions disambiguated automatically and one semantic index searching across all of them — a single agent can straddle domains: notes and calendars and tickets, or documents and analytics and messaging. Cross-system questions ("what did we promise this customer, and did we deliver?") become one plan whose steps touch different servers.

**A different persona per tenant, without new deployments.** Runtime overrides deep-merge onto a base configuration per request, so one deployed service can present a strict, formal agent to one customer and a casual, permissive one to another — different prompts, different tool policies, different budgets — with caching keeping every variant isolated by its signature. The runtime-bundle endpoint pushes this further: an external platform can *compose* agents dynamically — its users picking prompts and connectors in a UI — and run them here without the service knowing anything in advance.

**An evaluation and experimentation substrate.** Deterministic seeds, a synchronous endpoint, structured events, review verdicts, and per-run token counts are exactly the ingredients of an evaluation harness. Run a fixed question set through two prompt variants and compare grounding, verdicts, and cost; the framework does not ship the harness, but it produces every measurement the harness needs.

**A policy gateway for tool use.** Even an application that wants only "call one tool safely" gains from routing it through this service: schema validation, trusted argument injection, allow/deny policy, retries with backoff, deadlines, and a uniform event trail — the governance layer most direct tool integrations lack.

**An embedded orchestrator.** In library mode, a Python backend can run the whole loop in-process — no HTTP, no serialization — supplying a synchronous approver so destructive actions resolve inline with its own authorization logic, and injecting custom providers to reach systems that speak neither OpenAI nor MCP.

**Non-chat surfaces.** Nothing requires the answer to land in a conversation. The done event is a payload; a host can turn it into an email, a Slack message, a dashboard annotation, or a ticket comment. The agent is the reasoning engine; the delivery surface is the host's choice.

**And with modest extensions**, the same skeleton stretches further: a semantic memory provider fed by the shared resources section would give agents recall across sessions; the async migration would unlock parallel tool calls and true cancellation for high-concurrency products; an OpenTelemetry adapter would pour the existing event stream into standard observability stacks. Each of these slots into a seam that already exists — which is the point of building the framework as seams in the first place.

---

## 16. Current State: What It Can Do

Today, the service can: answer trivial messages instantly; plan multi-step work; discover tools dynamically across multiple MCP servers, by catalog or by semantic search; call tools with schema validation, policy enforcement, and trusted argument injection; pause destructive actions for human approval and resume them on any worker, surviving restarts with a durable store; review its own drafts and revise or replan within bounded cycles; render grounded, streamed final answers that are identical whether the caller used the synchronous or streaming endpoint; retry transient failures intelligently; account for every token spent; and serve many tenants from one process with credential-isolated caching.

Its known limits, stated plainly: execution is synchronous — each active run occupies a worker thread, which is comfortable at tens of concurrent runs per instance but is the ceiling to plan around, and true mid-flight cancellation of an in-progress model call is not possible until an async migration lands. There is no built-in semantic long-term memory — conversation history is whatever the caller passes in; a memory provider fed by the shared resources section is the designed next step. Observability data is complete but not yet exported to any metrics backend. And configuration versioning is content-addressed, not history-tracked — rollback is a job for version control.

---

## 17. Feature Support Summary

| Feature | Supported? | In short |
|---|---|---|
| Streaming | **Yes** | SSE end to end: status, plan, tool activity, review events, token-level answer deltas, and a final done event with usage. |
| Session/state persistence | **Yes, per run** | Checkpointed per thread; durable Redis/PostgreSQL stores make paused approvals survive restarts and load balancers. Finished threads are cleaned up. Long-term conversation memory is the caller's responsibility. |
| Tool registry + dynamic tool loading | **Yes** | No static registry: tools are discovered live from MCP servers (paginated catalogs, cached briefly) and/or a semantic vector index, filtered by per-agent policy. Tools are remote services, not loadable Python plugins. |
| Max loop/context guards | **Yes** | Executor turn caps, review/replan cycle caps, per-step tool caps, a search loop breaker, a graph recursion limit, token-budgeted context packing, and per-call deadlines. |
| Raw result storage | **Partial, by design** | Runs keep scored summaries plus compact structural references (counts, keys, identifiers) instead of raw payloads; the reference lets a host re-fetch the original. Full raw outputs are intentionally not persisted. |
| Tracing per node/tool call | **Partial** | Structured per-action events with tool latencies and statuses, per-run token usage, and log-context propagation into worker threads. No OpenTelemetry/metrics export yet. |
| Auth over HTTP | **Yes** | Fail-closed static API key with constant-time comparison, plus a config-directory allowlist and an outbound host allowlist. Single shared key — no per-tenant keys or OAuth. |
| Async execution & cancellation | **No** | The engine is synchronous and blocking. Client disconnects stop the stream and clean up state, and deadlines bound every call, but in-flight calls cannot be truly cancelled. The async migration is the known roadmap item. |
| Versioned agent configs | **Partial** | Every config is content-addressed by a cryptographic signature (which keys all caching, so changes take effect instantly and safely), and named configs live in an allowlisted directory. There is no built-in version history or rollback — that belongs to git. |
