# Agent Workflow Service Concepts

This document explains the concepts, technical terms, techniques, and features used by `agent-workflow-service`. It is intentionally verbal: no code snippets, no diagrams, and no application-specific business logic. The goal is to make the framework understandable as a reusable production AI Agent Development Kit.

## 1. What The Service Is

`agent-workflow-service` is a standalone runtime for configurable AI agents. A caller sends a user request, optional conversation history, a configuration reference, and trusted runtime context. The service then runs an agent loop that can plan, discover tools, call tools, retain evidence, review its own answer, stream progress, pause for human approval, and resume later.

The service is not tied to one application. It should be understood as a generic orchestration framework. A new product should usually add configuration, prompts, and MCP tools, not framework code.

## 2. Core Design Idea: Agents Are Configuration

The framework treats an agent as a configured behavior rather than hard-coded application logic. The configuration describes the model endpoint, prompts, tool servers, tool policies, loop limits, memory budgets, checkpointing resources, and safety rules.

This matters because the same runtime can support many agents. One agent can be a note assistant, another can be a document assistant, and another can be an operations assistant, while the runtime loop stays the same.

## 3. Agent Runtime

The agent runtime is the engine that executes a request. It validates the request, creates initial state, chooses whether to use a fast path or full workflow, runs the graph, translates graph updates into events, returns results, and cleans up checkpoints when a run is complete.

The runtime owns the lifecycle of a run. It decides when a run starts, when it pauses, when it resumes, and when it is terminal.

## 4. Run

A run is one execution of the agent for one user request. It has a user query, a session identifier, conversation history, runtime context, internal state, events, artifacts, tool calls, and a final result.

A run is not the same thing as a conversation. A conversation can have many runs. Each message turn can create a new run, and the runtime creates a unique thread identifier for each run so checkpoints do not collide.

## 5. Session ID

The session ID is the caller-provided logical grouping for a run. In a chat product, this is usually based on the conversation. In a multi-user product, it should include or be derived from server-trusted user or tenant identity so different users cannot accidentally share checkpoint state.

The service does not treat the session ID as authorization. It is an organizing key, not a security boundary.

## 6. Thread ID

The thread ID is the concrete checkpoint identity used by the graph. The runtime derives it from the session ID plus a random suffix. This makes every run unique even if several turns belong to the same conversation.

Thread IDs are especially important for pause and resume. If a run pauses for approval, the thread ID is what lets the caller resume the exact saved state later.

## 7. Runtime Context

Runtime context is trusted metadata supplied by the host application. It can contain values such as user ID, tenant ID, role, workspace ID, active resource IDs, feature switches, or other server-derived facts.

Runtime context is different from the user message. The model should not invent these values, and the browser should not be trusted to provide them directly. The framework validates runtime context shape, limits nesting and list sizes, and blocks known prototype-pollution keys.

Runtime context becomes most powerful when combined with argument injection. It lets the framework stamp trusted values into tool calls even if the model omitted or attempted to override them.

## 8. Conversation History

Conversation history is recent prior chat context. The service accepts history as structured messages and includes a bounded slice in model context. History helps resolve follow-up questions, but it must be controlled because it can grow quickly and consume token budget.

The framework treats history as contextual input, not durable memory. Long-term memory should come through tools or external storage.

## 9. Agent State

Agent state is the working memory of one run. It includes the user request, history, runtime context, plan, current step, candidate tools, tool discovery cache, artifacts, recent tool calls, review feedback, iteration counters, phase, final answer, errors, events, and any pending destructive action.

State is the key to iterative understanding. If candidate tools, failed attempts, artifacts, and open feedback are preserved in state, the agent can reason across turns instead of restarting from scratch every step.

## 10. Phase

Phase is the run's current mode. The phases are planning, executing, awaiting approval, compacting, fact extracting, synthesizing, reviewing, revising, and done.

The phase controls routing through the graph. Planning routes to execution. Execution routes back to itself, to approval, to the summarizer for memory compaction, or forward to fact extraction once the plan is complete. Fact extraction routes to synthesis; synthesis routes to review or straight to finalization; review routes to a single revision pass or to finalization; revision routes to finalization. Approval and the summarizer both return to execution. Notably, review never routes back to the executor — a revision is a separate, bounded rewrite — which is what prevents review-execute loops.

## 11. LangGraph

LangGraph is the graph runtime used to connect the agent nodes. Each node reads state and returns updates. Conditional edges decide which node runs next.

Using a graph makes the loop explicit. Instead of a hidden while loop, the framework has named nodes, named phases, checkpointed transitions, and a clear resume model.

## 12. Graph Nodes

A graph node is a unit of agent behavior. This service has planner, executor, approval, summarizer, fact extractor, synthesizer, reviewer, revision, and finalizer nodes.

Each node has one job, and the separation is deliberate. The planner decomposes the request. The executor orchestrates tools only — it never writes the final answer. The approval node handles destructive actions. The summarizer compacts memory mid-loop. The fact extractor deterministically distills artifacts into compact facts. The synthesizer writes the single draft answer from those facts. The reviewer judges the draft without rewriting it. The revision node applies one bounded rewrite when the reviewer asks. The finalizer renders or reuses the terminal answer.

## 13. Router And Fast Path

Before the full graph runs, the engine checks whether the request is simple enough for a direct answer. Greetings, simple arithmetic, and short explicitly ungrounded questions can use the fast path.

The fast path avoids planning, tools, review, and finalization. It exists for latency and cost. It is conservative: anything that looks tool-related, complex, or document-related goes through the full workflow.

The host can force the full agent path through runtime context. This is useful when the application knows a short message still requires tools.

## 14. Planner

The planner turns the user request into a goal, steps, tool hints, assumptions, risks, and acceptance criteria. It is useful for multi-step tasks that need decomposition.

The planner can be disabled. When disabled, the engine creates a single implicit step from the user request and starts execution immediately. This is often better for retrieval-heavy agents where planning adds latency without much benefit.

## 15. Plan

A plan is the agent's task structure. It gives the executor a current step and gives the reviewer acceptance criteria.

A good plan is short, concrete, and tool-shaped. A poor plan is vague and causes the executor to wander. In this framework, plan quality strongly affects loop quality.

## 16. Executor

The executor is the main agent loop. On each turn, it sees the current state and chooses one action: search for tools, call a tool, or finish the current step. A direct draft action also exists but is only a fallback; on the normal path the executor finishes its steps and hands off, leaving authoring to the synthesizer.

The executor is intentionally constrained to one action per turn. This makes tool policy enforcement, approval gates, event streaming, retries, and state updates predictable. When the last plan step finishes, the executor hands off to deterministic fact extraction rather than writing the answer itself — authoring belongs to the synthesizer, not the tool loop.

## 17. Executor Iteration

Executor iteration is one pass through the executor node. The service counts executor turns and stops at a configured maximum. This prevents infinite loops and controls cost.

When the iteration limit is reached, the framework tries to synthesize the best available answer from existing artifacts instead of failing with nothing.

## 18. Tool Discovery

Tool discovery is the process of finding tools relevant to the current step. The executor can ask the tool provider to search tools based on a query derived from the current step and user request.

Discovery results become candidate tools in state. They should remain visible to the executor until the step finishes, so the agent does not repeatedly rediscover the same tools and forget that they exist.

## 19. Candidate Tools

Candidate tools are the currently discovered tools for the active step. They include names, titles, descriptions, scores, and input schemas.

Candidate tools are important working memory. They tell the model what tools are available and how to call them. If candidate tools are erased too early, the agent can incorrectly conclude that a tool does not exist.

In this service, candidate tools are cleared when a step finishes, because the next step may need a different tool set.

## 20. Tool Discovery Cache

The tool discovery cache remembers tool search results inside the run. It is keyed by a normalized search query and retained under a configured size limit.

This prevents repeated semantic searches from hammering tool servers or indexes. It also helps the agent stay coherent: if it searches the same need again, it gets the same candidates from memory.

## 21. Search Loop Breaker

A search loop breaker is a safeguard for agents that repeatedly search for tools even though candidate tools are already available.

The service detects repeated searches within the same step. First it reminds the executor that candidate tools already exist. If the pattern continues, it forces progress by selecting a candidate tool or finishing the step. This prevents the agent from spinning forever in discovery.

## 22. Tool Provider

A tool provider is the framework abstraction for discovering and calling tools. The executor does not know whether tools come from one MCP server, many MCP servers, or a semantic tool index. It only knows how to search for candidates and call a named tool.

This abstraction is one reason the framework is reusable. Applications can expose different tools without changing the executor.

## 23. MCP

MCP means Model Context Protocol. In this service, MCP is the main way external tools are exposed to the agent. MCP servers advertise tool catalogs and execute tool calls.

The framework treats MCP servers as external services. It initializes the MCP connection, lists tools, calls tools, normalizes results, handles pagination, applies authentication tokens, and closes clients when appropriate.

## 24. MCP Tool Catalog

The MCP tool catalog is the list of tools exposed by an MCP server. Each tool typically has a name, title, description, and input schema.

Catalogs are cached for a short time. This reduces repeated network calls while still allowing tool definitions to update without restarting the agent service.

## 25. Multi-MCP Support

The service can connect to multiple MCP servers. When tool names collide, the framework disambiguates them by exposing prefixed names. This avoids ambiguity while still allowing several domains to be available in the same agent.

Multi-MCP support lets one agent work across systems, such as notes, documents, tickets, calendars, databases, or internal APIs.

## 26. Semantic Tool Search

Semantic tool search means finding tools by meaning instead of exact name. The service supports semantic search in two ways: an MCP server can expose a semantic tool search tool, or the configuration can point to an HTTP tool index.

Semantic search is useful when there are many tools. The agent can ask for a capability in natural language and receive the most relevant tools.

## 27. Tool Index

A tool index is an external searchable index of tool descriptions. It can be backed by vector search or another retrieval system. The service queries it to find likely tools before falling back to catalog ranking.

The tool index is optional. If unavailable, the framework ranks the MCP catalog locally using lexical overlap and metadata.

## 28. Local Tool Ranking

Local tool ranking is the fallback discovery method. The framework tokenizes the search query and tool metadata, then ranks tools by overlap and relevance signals.

This is less powerful than semantic search but robust because it requires no separate index.

## 29. Tool Policy

Tool policy controls what the agent may do with tools. It includes allowlists, denylists, required tools, destructive tools, per-step tool call limits, and argument injection.

Tool policy is a safety and quality layer. It prevents the model from seeing or using tools outside the intended scope and forces important tools to be used before a step can be considered complete.

## 30. Allowlist

An allowlist is the set of tools the agent is allowed to use. If an allowlist exists, any tool not listed is blocked.

Allowlists are useful when an MCP server exposes many tools but a specific agent should use only a few.

## 31. Denylist

A denylist is the set of tools the agent must not use. Denylists override general availability.

Denylists are useful for tools that exist on a server but are too risky, irrelevant, or not ready for a particular agent.

## 32. Required Tools

Required tools are tools that must be called before a plan step can finish. They can be declared directly on a step or through policy rules matching step titles.

Required tools help prevent shallow answers. For example, a retrieval step can require a search tool so the executor cannot skip evidence gathering and jump straight to a draft.

## 33. Argument Injection

Argument injection means the framework overrides or fills selected tool arguments from trusted runtime context. For example, a user-scoped tool can always receive the server-derived user ID, regardless of what the model wrote.

This is one of the most important multi-tenant safety features. The model chooses the tool and some arguments, but the framework controls sensitive arguments.

## 34. Tool Argument Validation

Before a tool call runs, the framework validates arguments against the tool's JSON schema. It checks required fields, basic JSON types, and unexpected fields when the schema forbids additional properties.

Invalid arguments become tool-call records with an invalid-argument status. The model can then see that failure in context and try again with corrected arguments.

## 35. Native Tool Calling

Native tool calling uses the model provider's tool-calling protocol instead of asking the model to write a JSON action in text. The framework prefetches candidate tools and gives their schemas to the model as callable tools.

Native mode can reduce latency because the model can select and call a tool directly. The framework still validates policy, schema, injected arguments, destructive gates, and one-action-per-turn behavior.

If the model endpoint does not support native tool calling, the executor falls back to the text-based action mode.

## 36. Classic JSON Action Mode

Classic mode asks the model to return a structured action in text. The possible actions are tool search, tool call, finish step, or draft answer.

This mode works with any normal chat-completions-compatible model. It is more universal than native tool calling but usually costs more reasoning turns.

## 37. One Action Per Turn

The executor processes one action per turn. Even if a model returns multiple native tool calls, the framework executes only the first and defers the rest.

This design keeps the loop auditable. Every tool call becomes a separate state transition with its own policy check, approval check, artifact, event, and opportunity for review.

## 38. Destructive Tools

Destructive tools are tools that can change or delete data, send messages, trigger external side effects, or perform irreversible operations. The configuration names them explicitly.

When destructive confirmation is enabled, these tools cannot run silently. They either require a synchronous host approver or cause the run to pause for human approval.

## 39. Human-In-The-Loop Approval

Human-in-the-loop approval is the pause-and-resume mechanism for destructive actions. If the executor selects a destructive tool and no synchronous approver is present, the run saves pending action details and enters the awaiting-approval phase.

The caller receives a pending approval event and a thread ID. Later, the caller resumes the same thread with an approval or denial decision.

## 40. Approval Node

The approval node handles resumed destructive actions. If approved, it executes the pending tool call and records the result as an artifact. If denied, it records the denial and returns control to the executor.

A denied destructive tool is remembered so the executor does not ask for the same denied action forever.

## 41. Reviewer

The reviewer checks the draft answer against the plan, acceptance criteria, tool results, and evidence. It can approve, request revision, or reject. It is a judge only: it never rewrites the answer. Its parsing is layered — it accepts a verdict as JSON or markdown and falls back to a safe revise when the reply cannot be parsed — and before it accepts an approval it runs deterministic completion checks that can override an over-eager verdict.

Reviewer behavior is configurable. It can run on every run or only when deterministic risk signals exist, such as failed tool calls, denied tools, or errors.

## 42. Review Verdicts

An approve verdict allows finalization. A revise verdict routes to a single bounded revision pass — not back to the executor — which rewrites the draft from the same evidence and then finalizes. A reject verdict returns the best available draft; routing back to the planner ("replan") is a configured option that is not currently wired, so in practice reject behaves like abort.

Review and revision cycles are capped. Because revision is a separate node with no edge back to the executor, there is no revise-execute spiral.

## 43. Risk-Gated Review

Risk-gated review means the reviewer is skipped on clean runs and used only when the run shows risk. This reduces model calls while still checking problematic runs.

Risk signals include errors and non-successful tool calls. This mode is useful after an agent has been tuned and the always-on reviewer is no longer needed for every request.

## 44. Finalizer

The finalizer produces the final user-facing answer. It can render a mechanical draft into natural prose and stream the generated answer token by token.

The finalizer can be disabled. If disabled, the draft answer becomes the final answer.

## 45. Conditional Finalization

Conditional finalization means the finalizer skips extra model work when the draft is already acceptable prose. This saves latency and cost.

Mechanical drafts, such as artifact summaries, usually benefit from final rendering. LLM-written drafts may not.

## 46. Grounding

Grounding means answers should be supported by tool artifacts. The framework favors grounded answers by retaining artifacts, putting them in context, using mechanical fallback answers, and optionally enforcing source references.

Grounding does not mean the model is always correct. It means the runtime tries to keep evidence visible and gives the reviewer and finalizer material to cite.

## 47. Artifact

An artifact is the framework's compact memory record of a tool result. It includes the tool name, summary, raw reference, source reference, scores, creation time, step index, and truncation flag.

Artifacts are the main evidence objects in the run. They are retained across executor turns and used by the reviewer and finalizer.

## 48. Raw Reference

A raw reference is a compact description of the original tool result. It records things like result type, keys, counts, identifiers, and truncation status.

The raw reference is not the full raw payload. It is a lightweight pointer or fingerprint that helps the run understand what was returned without bloating state.

## 49. Source Reference

A source reference identifies where evidence came from. It may include document IDs, chunk IDs, pages, paths, URLs, or other source metadata.

Source references support citation and auditability.

## 50. Artifact Scoring

Artifact scoring ranks tool results so the most useful evidence survives when memory is limited. The service scores relevance, freshness, uniqueness, and actionability, then combines them into a composite score.

Relevance estimates whether the artifact matches the current step. Freshness favors newer data. Uniqueness penalizes duplicate evidence. Actionability favors results with identifiers, rows, matches, or concrete objects.

## 51. Artifact Pruning

Artifact pruning removes lower-scoring artifacts when the retained artifact limit is exceeded. This keeps state bounded while preserving the most useful evidence.

Pruning is essential for long-running agents because unbounded tool results would eventually overwhelm both memory and model context.

## 52. Tool Call Record

A tool call record is the audit entry for a tool attempt. It stores the tool name, argument preview, status, latency, and error if present.

Tool call records help the model learn from failures during the same run, help the reviewer judge reliability, and help operators debug behavior.

## 53. Event

An event is a structured description of something that happened during the run. Events include planning, tool discovery, tool calls, invalid arguments, approval requests, review results, final answers, debug messages, and usage telemetry.

Events are used for streaming UIs, logs, debugging, and operational monitoring. The retained event list is capped so it does not grow without bound.

## 54. Context Builder

The context builder decides what the model sees on each planner, executor, or reviewer call. It assembles sections such as user request, plan, candidate tools, artifacts, recent tool calls, reviewer feedback, conversation history, and draft answer.

Each section has a priority. Higher-priority sections are admitted first under the token budget.

## 55. Context Packing

Context packing is the process of fitting the most important state into the model's token budget. The service does not simply dump all state into the prompt.

The artifact section receives special treatment: if it does not fully fit, it can be trimmed instead of dropped entirely. This helps preserve grounding even when context is tight.

## 56. Token Budget

The token budget is the configured maximum amount of context the framework will send to the model. It protects cost, latency, and model reliability.

A larger token budget can improve recall but increases cost and latency. A smaller budget is faster but can starve the model of evidence.

## 57. Truncation

Truncation compresses large tool results into bounded summaries. Strings, dictionaries, and lists are handled differently. The framework preserves representative rows, important keys, counts, identifiers, and a truncation flag.

Truncation is not just shortening text. It is structured compression designed to preserve usefulness while controlling context growth.

## 58. Mechanical Draft

A mechanical draft is a deterministic answer assembled from artifacts rather than invented by the model. It is used when the executor needs a safe fallback or when the run reaches limits.

Mechanical drafts are usually less polished but more grounded.

## 59. LLM Draft

An LLM draft is a model-written answer created from the current context and artifacts. It can be more natural than a mechanical draft, but it still needs review and finalization depending on policy.

## 60. Fallback Answer

A fallback answer is the best answer the service can provide when something goes wrong or limits are reached. It uses gathered artifacts when possible and avoids pretending that failed steps succeeded.

Fallback behavior is a reliability feature. It gives the caller useful information instead of a blank failure.

## 61. Checkpointing

Checkpointing saves graph state under a thread ID. It makes pause-and-resume possible and lets durable stores preserve pending approvals across workers or restarts.

The service supports memory, Redis, and PostgreSQL-style checkpoint modes. Memory is suitable for local development. Redis or PostgreSQL is appropriate for production and horizontal scaling.

## 62. Shared Checkpointer

A shared checkpointer is reused across engines that reference the same checkpoint resource. This avoids creating unnecessary connections and lets multiple cached engines share durable state infrastructure.

## 63. Resume

Resume continues a paused run. It loads the checkpoint for a thread ID, applies an approval or denial decision, and streams or returns the continuation.

Resume only makes sense for a run that is actually awaiting approval. If no pending action exists, the service returns a done event with an explanatory error.

## 64. Cleanup

Cleanup deletes checkpoint state for terminal runs. Runs awaiting approval are not cleaned up, because their checkpoint is needed for resume.

Cleanup also happens on client disconnect for non-paused runs, preventing abandoned streams from leaving unnecessary checkpoint state behind.

## 65. Recursion Limit

The recursion limit is the LangGraph safety cap for graph transitions. The service calculates it from executor iteration limits and review-cycle limits.

If the recursion limit is reached, the service returns a best-effort answer and records an error event. This protects production systems from runaway loops.

## 66. Deadlines

Deadlines wrap external model and tool calls. A deadline is a hard upper bound on how long the framework waits for a call.

Deadlines are different from transport timeouts. Transport timeouts belong to HTTP clients. Deadlines protect the agent loop as a whole so hung dependencies cannot hold a run forever.

## 67. Retry

Retry means repeating transient failures, such as server errors, rate limits, or temporary network issues. The framework distinguishes transient errors from permanent client errors.

Streaming retries are careful: if no token has been emitted, a stream can retry safely. If tokens already reached the caller, retrying could duplicate text, so the framework does not retry mid-answer.

## 68. HTTP Provider

The HTTP provider is the abstraction used for OpenAI-compatible chat completions. It supports normal completions, streaming completions, native tool calls, authentication headers, sampling parameters, usage tracking, and connection reuse.

The model provider is generic. The runtime expects a chat-completions-like API, not a specific model vendor.

## 69. Usage Tracking

Usage tracking records prompt, completion, and total tokens reported by the model provider. The engine snapshots usage before and after a run, then emits the delta as telemetry.

Usage data is important for cost attribution, capacity planning, and evaluating prompt or policy changes.

## 70. Provider Cache

Provider caching reuses LLM and tool provider instances for identical agent configurations. This avoids reconnecting to model and MCP servers on every request.

The cache key is based on a configuration signature, so different credentials or settings do not accidentally share providers.

## 71. Graph Cache

Graph caching reuses compiled LangGraph graphs. Compiling a graph is more expensive than running it, so compile-once reuse improves throughput.

The graph cache includes provider identity and checkpointer identity in its key because compiled graphs close over those runtime objects.

## 72. Configuration Signature

A configuration signature is a stable digest of the agent configuration. It includes behaviorally relevant configuration but hashes sensitive values rather than exposing them.

The signature isolates cache entries. Two agents with different settings should not share runtime objects accidentally.

## 73. Agent Configuration

Agent configuration is the product surface of the framework. It defines identity, prompts, model settings, MCP settings, policies, and shared resources.

For a reusable framework, configuration is where application-specific behavior belongs.

## 74. Prompts

Prompts are role-specific instructions for planner, executor, and reviewer. They can be stored as files or provided inline.

Prompts should describe domain behavior and expectations. The framework supplies loop mechanics, but prompts shape judgment, style, and task interpretation.

## 75. Policy Instructions

Policy instructions are additional agent-level instructions appended to role prompts. They let a configuration add behavior without editing shared prompt files.

This is useful for tenant-specific or app-specific guidance.

## 76. Model Settings

Model settings include base URL, model name, API key, whether to send authorization headers, max token defaults, temperature, top-p, top-k, seed, and whether native tool calling is enabled.

These settings let each agent choose the right model behavior without code changes.

## 77. MCP Settings

MCP settings describe one default MCP server or many named servers. Each server can have a URL, auth token, timeout, TLS verification setting, proxy URL, and tool discovery settings.

This lets the same runtime connect to different tool ecosystems per agent.

## 78. Resources

Resources describe shared infrastructure used by the runtime. The main resources are checkpointing and tool index search.

Keeping resources in configuration makes deployments explicit and lets the engine reuse connections across compatible agents.

## 79. Runtime Overrides

Runtime overrides are request-time configuration changes merged onto a base config. They allow a host platform to customize an agent per tenant, user, or session while still using the same deployed service.

Runtime overrides are validated and subject to outbound host allowlisting.

## 80. Runtime Bundle

A runtime bundle is an externally assembled description of an agent, often coming from another platform. The service adapts the bundle into normal runtime overrides.

This supports agent builders or marketplaces where users select models, instructions, connectors, and active tools dynamically.

## 81. Config Path Resolution

The API can load named configs from an allowlisted directory. It rejects paths outside that directory and rejects missing files.

This prevents callers from using the service to read arbitrary files from the container.

## 82. Outbound Host Allowlist

The outbound host allowlist restricts which hosts can appear in model URLs, MCP URLs, tool index URLs, and checkpoint URLs supplied by configs or overrides.

This is a server-side SSRF defense. Without it, a caller with config access could make the service connect to internal metadata services or unauthorized hosts.

## 83. API Key Authentication

The HTTP API is protected by an `X-API-Key`-style service key. If no service key is configured, the service fails closed and rejects requests.

This is service-to-service authentication, not end-user authentication. The host application is responsible for authenticating users and deriving trusted runtime context.

## 84. Request Validation

Requests are validated with strict schemas. Query length, session ID length, history length, message roles, message content length, runtime context shape, and config fields are bounded.

Strict validation protects reliability and prevents malformed requests from creating strange loop behavior.

## 85. SSE Streaming

SSE means Server-Sent Events. The stream endpoint emits events as text chunks over one HTTP response.

Streaming lets callers show progress: planning status, tool searches, tool calls, review results, answer deltas, pending approvals, and final completion.

## 86. Engine Events

Engine events are internal event dictionaries generated during a run. The API adapter maps them to SSE event names and payloads.

This separation allows the core library to be used without HTTP while the service still exposes a clean streaming protocol.

## 87. Event Types

Important event types include metadata, status, plan, agent activity, review, delta, pending approval, debug, error, and done.

Agent activity events are useful for UI status. Delta events carry answer text. Done events carry the final answer, review, counts, usage, errors, pending approval details, and thread ID.

## 88. Host Callbacks

Host callbacks are hooks that an embedding application can provide when using the engine as a library. They can observe plans, tool searches, tool calls, artifacts, reviews, generic events, and destructive actions.

A synchronous destructive-action callback can approve or deny a tool inline, avoiding the pause-and-resume flow for interactive hosts.

## 89. Library Mode

Library mode means using the engine directly in Python instead of through HTTP. The same runtime, graph, events, and resume behavior are available.

Library mode is useful for tests, command-line agents, or applications that want in-process orchestration.

## 90. Service Mode

Service mode means running the FastAPI app and using HTTP endpoints. This is better for multi-language applications, independent scaling, containerized deployment, and centralized agent governance.

## 91. Synchronous Run Endpoint

The synchronous run endpoint executes a run and returns the final result in one response. It is useful for batch jobs, tests, automations, or backend workflows where streaming is not needed.

## 92. Stream Endpoint

The stream endpoint executes a run and emits progress events as they happen. It is useful for chat UIs and long-running workflows.

## 93. Resume Endpoint

The resume endpoint continues a paused approval run. It accepts a thread ID and an approve-or-deny decision, then returns the final result.

A streaming resume method also exists at the engine layer, allowing resumed runs to emit progress.

## 94. Health Endpoint

The health endpoint reports basic service liveness. It is intended for deployment probes and simple operational checks.

## 95. Error Handling

The service tries to turn failures into structured results. Tool failures become tool call records. Model deadlines become timeout events. Graph recursion becomes a best-effort answer. HTTP validation failures return API errors.

The guiding principle is that a production agent should fail informatively and preserve evidence already gathered.

## 96. Transient Error Classification

Transient errors are failures likely to succeed if retried, such as server errors, rate limits, timeouts, and temporary network failures. Permanent errors are failures caused by bad requests or invalid configuration.

The retry layer uses this distinction to avoid wasting time retrying permanent failures.

## 97. Connection Pooling

LLM and MCP providers reuse HTTP clients. This reduces connection overhead and improves throughput under concurrent traffic.

Providers expose close behavior so cached resources can be cleaned up when evicted or when the service shuts down.

## 98. Concurrency

The service can support concurrent users by keeping per-run state isolated, generating unique thread IDs, using shared durable checkpointing, reusing stateless cached providers safely, and avoiding global mutable user state.

For production, memory checkpointing is not enough. Redis or PostgreSQL checkpointing is needed when multiple service replicas can handle runs and resumes.

## 99. Horizontal Scaling

Horizontal scaling means running multiple instances of the service behind a load balancer. This works when state needed across requests is in a shared checkpoint store and when model/tool providers point to external services.

Paused approval runs can resume on any replica only if the checkpoint store is shared.

## 100. Multi-Tenancy

Multi-tenancy means serving multiple users, teams, or organizations safely from the same runtime. The framework supports this through trusted runtime context, argument injection, config isolation, cache signatures, tool policies, and outbound host allowlisting.

The framework does not replace application authorization. The host application must authenticate users and pass only trusted scope values.

## 101. State Isolation

State isolation means one run's artifacts, candidate tools, tool calls, and review feedback cannot leak into another run. The framework creates fresh initial state for every run and caches only configuration-level providers and graphs.

This is critical for both correctness and privacy.

## 102. Iterative Understanding

Iterative understanding is the ability to preserve what the agent has learned while it works through a task. In this service, iterative understanding comes from retained artifacts, retained tool calls, candidate tools, discovery cache, review feedback, and the current plan step.

If these are pruned too aggressively or not included in context, the model may repeat searches, forget failures, or conclude that tools do not exist.

## 103. Recovery From Weak Results

A weak or empty tool result should not mean the tool is missing. It should become an observation that informs the next action.

The framework supports this by retaining failed tool calls and artifacts, exposing recent tool calls in context, and letting the executor try broader searches, alternate tools, or a different step before giving up.

## 104. Step Completion

Step completion means the executor decides the current plan step is done. The framework checks required tools before allowing completion. When a step finishes, the current step index advances and candidate tools are cleared for the next step.

Clearing candidate tools per step is correct only if artifacts and tool call records remain available. The next step should not lose evidence, only step-specific tool candidates.

## 105. Per-Step Tool Limit

The per-step tool limit caps how many different tools can run for one plan step. If the cap is reached, the executor is forced to finish the step.

This prevents exploratory loops from burning unbounded tool calls.

## 106. Duplicate Tool Prevention

The executor detects when the same tool has already been called for the current step and can skip duplicate calls. This avoids the model repeatedly overwriting its own choice.

Duplicate prevention is a loop-control technique, not a guarantee that the first call was semantically sufficient.

## 107. Tool Result Normalization

MCP tool results can come in different shapes. The provider normalizes structured content, text content, and plain payloads into a consistent object for the executor.

Normalization lets downstream truncation, scoring, artifact creation, and source extraction work consistently.

## 108. Pagination

MCP tool listing can be paginated. The provider follows cursors for a bounded number of pages.

Pagination support matters when servers expose many tools.

## 109. Catalog TTL

Catalog TTL is the time window for reusing a loaded MCP tool catalog. It balances freshness against performance.

A short TTL sees updates sooner but increases network calls. A long TTL reduces load but may delay tool changes.

## 110. Proxy Support

MCP server configuration can include a proxy URL. This lets deployments route tool traffic through controlled network paths when needed.

## 111. TLS Verification

MCP server configuration can control TLS verification. Production deployments should generally keep verification enabled unless using a controlled private network with known constraints.

## 112. Model Sampling

Sampling settings such as temperature, top-p, top-k, and seed influence model behavior. Lower randomness tends to improve reproducibility and schema following. Higher randomness can improve creative phrasing but may hurt deterministic tool use.

For agent workflows, conservative sampling is usually better.

## 113. Model Choice

The configured model should be strong enough to follow instructions, use tools, parse schemas, recover from errors, and synthesize grounded answers. Weak models may work for fast path responses but struggle with multi-step execution.

The framework can enforce many rules, but the model still needs enough reasoning ability to choose good next actions.

## 114. Prompt Roles

Planner, executor, and reviewer prompts serve different purposes. The planner prompt should produce practical steps. The executor prompt should preserve state, use tools, and obey action format. The reviewer prompt should judge evidence and acceptance criteria.

Mixing these roles into one prompt usually makes behavior less reliable.

## 115. Acceptance Criteria

Acceptance criteria are conditions the final answer should satisfy. They give the reviewer something concrete to check.

Without acceptance criteria, review becomes generic quality judgment rather than task-specific verification.

## 116. Reviewer Feedback

Reviewer feedback is stored in state and consumed by the revision node; it is also available to planner and executor context. It tells the bounded rewrite what was missing or wrong.

This is how the agent improves within a run rather than simply being judged at the end.

## 117. Replanning

Replanning is the idea of returning to the planner when the reviewer rejects the current approach. The configuration exposes a reject action for this, but the edge is not currently wired: a reject verdict returns the best available draft instead. The honest current setting is abort, and the configuration and docs are kept consistent with that.

The design keeps replanning bounded by review-cycle limits for when it is implemented, because repeated replanning can otherwise become expensive and unproductive.

## 118. Final Answer Rendering

Final answer rendering is the final LLM pass that turns evidence and draft content into a polished response. It can stream output through custom graph events.

Rendering improves user experience but costs an extra model call when not skipped.

## 119. Source Enforcement

Source enforcement attempts to append or preserve source references when grounding is required. This helps prevent answers from losing evidence during final phrasing.

It is a guardrail, not a replacement for good retrieval and artifact quality.

## 120. Debug Events

Debug events explain internal decisions such as executor actions, repeated searches, invalid arguments, skipped duplicate tools, loop breakers, and errors.

These events are valuable during development and evaluation. In production UIs, they may be hidden or shown only in developer mode.

## 121. Agent Activity Events

Agent activity events are user-facing progress updates. They describe tool search, tool calls, approval blocks, and review phases.

They are suitable for chat UIs that want to show what the agent is doing without exposing every internal detail.

## 122. Delta Events

Delta events carry streamed answer text. They are emitted by fast-path streaming and finalizer streaming.

Clients append deltas to build the visible assistant response.

## 123. Done Event

The done event is the terminal event for a stream. It includes final answer information, review data, artifact count, tool call count, errors, pending approval details if any, usage, and thread ID.

Clients should treat done as the authoritative end of the run.

## 124. Pending Approval Event

A pending approval event means the run has paused before executing a destructive tool. It includes the thread ID, tool name, arguments, step index, query, and request time.

The caller should present this to an authorized human or policy engine and then call resume.

## 125. API Response Envelope

The HTTP API wraps JSON responses in a consistent success/failure envelope. This makes sync results and errors easier for clients to consume.

Streaming responses use SSE instead of this envelope for each event.

## 126. Environment Resolution

Configuration values can reference environment variables. They are resolved when the config is parsed.

This keeps secrets and deployment-specific URLs out of committed config files.

## 127. Secret Handling

Secrets such as model keys and MCP tokens are accepted through configuration or environment, but signatures hash them rather than exposing them directly.

Operationally, secrets should be provided by deployment secret management, not hard-coded into repository files.

## 128. Import Isolation

The service is structured so the runtime can be imported as a library without accidentally depending on the HTTP app layer. Tests cover import isolation.

This supports reuse in non-service contexts.

## 129. Test Fakes

The test suite uses fake LLM and tool providers to exercise the graph without real network services. This makes behavior deterministic and keeps framework tests focused on orchestration logic.

Testability is a feature of the provider abstraction.

## 130. Runtime Security

Runtime security includes API key checks, config path restrictions, outbound host allowlisting, strict schemas, runtime context validation, tool policy, argument injection, destructive gates, and checkpoint cleanup.

No single mechanism is enough. The framework relies on layered defenses.

## 131. Production Reliability

Production reliability comes from bounded loops, timeouts, retries, checkpointing, fallback answers, structured errors, connection pooling, cache isolation, and cleanup.

An agent framework must assume models and tools will fail sometimes. The runtime should recover, report, and stop safely.

## 132. Performance Optimization

Major performance features include fast path routing, optional planner, native tool calling, conditional finalizer, risk-gated reviewer, provider caching, graph caching, catalog caching, discovery caching, bounded context packing, deterministic fact extraction, a single synthesis pass, and in-loop memory compaction.

These reduce model calls, network calls, and token usage without removing safety controls.

## 133. Cost Control

Cost is mainly driven by model calls and token volume. The framework controls both with loop limits, context budgets, truncation, reviewer modes, finalizer skipping, and fast path routing.

Cost should be monitored through usage telemetry and evaluated per agent configuration.

## 134. Observability

Observability means understanding what happened during a run. The service provides structured events, tool call records, artifact counts, review verdicts, errors, latency in tool records, and token usage.

A production deployment should log or collect these events for debugging, evaluation, and cost analysis.

## 135. Evaluation

Evaluation is the process of testing agent behavior against known tasks. This framework supports evaluation through deterministic request handling, sync run endpoints, structured events, review verdicts, tool-call traces, and usage data.

Good evaluations should inspect not only final answers but also whether the agent used the right tools and recovered from weak results.

## 136. Reusable ADK Boundary

The reusable framework boundary is the line between generic orchestration and application behavior. Generic orchestration belongs in `agent-workflow-service`. Application behavior belongs in prompts, configs, MCP tools, and host runtime context.

Maintaining this boundary keeps the service reusable across applications.

## 137. Application Integration Pattern

The recommended integration pattern is for an application backend to authenticate the user, derive trusted runtime context, choose an agent config, call the agent workflow service, stream events to the frontend, and expose MCP tools through separate services.

The browser should not directly choose trusted identities or sensitive tool arguments.

## 138. Notelite Agent Configuration

The Notelite configuration is an example of using the generic framework for one product. It allowlists read-only note tools, injects user identity into tool arguments, disables the planner for lower-latency retrieval, enables review and grounding, and uses Redis checkpointing when configured.

This configuration demonstrates how product-specific behavior should live outside the framework loop.

## 139. Common Failure: Amnesiac Tool Use

A common agent failure is forgetting discovered tools or previous weak results. The symptom is repeated tool discovery, repeated calls, or claims that a tool does not exist even though it was listed earlier.

The correct fix is not merely better prompting. The run must retain candidate tools, discovery cache, recent tool calls, artifacts, and failure observations, and the context builder must include them under the token budget.

## 140. Common Failure: Premature Final Answer

Another common failure is answering after one weak tool result. Required tools, reviewer feedback, acceptance criteria, and prompts that require evidence can reduce this.

The executor should treat weak results as information for the next search strategy, not as proof that the task is impossible.

## 141. Common Failure: Context Bloat

Context bloat happens when too much history, too many tool results, or too many events are sent to the model. It increases cost and can make the model less reliable.

The framework fights this with truncation, scoring, retention caps, and priority-based context packing.

## 142. Common Failure: Unsafe Tool Scope

Unsafe tool scope happens when a model can choose tenant identifiers, user identifiers, or resource scopes directly. This can cause cross-user access or accidental modification.

Argument injection and server-derived runtime context are the main defenses.

## 143. Common Failure: Runaway Loops

Runaway loops happen when an agent repeats discovery, calls tools without progress, revises forever, or replans forever.

The framework uses executor iteration limits, per-step tool limits, review-cycle limits, recursion limits, duplicate prevention, and search loop breakers to stop this.

## 144. When To Enable Planner

Enable the planner for genuinely multi-step, cross-tool, analytical, or operational tasks. Disable it for simple retrieval agents where almost every question is one step: find evidence and answer.

Planner cost is justified only when decomposition improves the result.

## 145. When To Enable Reviewer

Enable the reviewer while developing and for high-stakes workflows. Consider risk-gated review after prompts and tools are stable.

Reviewer cost is worth paying when correctness and grounding matter more than latency.

## 146. When To Enable Native Tool Calling

Enable native tool calling when the model endpoint supports the OpenAI tools contract reliably. It can improve tool selection and reduce reasoning turns.

Keep fallback behavior available because not all model servers support tool calling fully.

## 147. When To Use Durable Checkpointing

Use durable checkpointing whenever there are multiple service replicas, long-running approvals, production traffic, or any need to resume after process restarts.

Use memory checkpointing only for local development and tests.

## 148. When To Use Runtime Bundles

Use runtime bundles when another platform dynamically defines agents, prompts, connectors, and active tools. Use named config files when agents are known ahead of deployment.

Runtime bundles are powerful but should be paired with strict host allowlisting and policy validation.

## 149. How To Extend The Framework

To extend the framework for a new application, add MCP tools, write prompts, create an agent config, set tool policy, pass trusted runtime context, and tune budgets.

Avoid adding application-specific logic to planner, executor, reviewer, or finalizer nodes unless the behavior is truly generic.

## 150. The Mental Model

Think of the service as a governed, checkpointed, tool-using reasoning loop. The model proposes actions, but the framework decides what is allowed, validates inputs, injects trusted scope, records evidence, controls memory, checks the answer, streams events, and stops safely.

The model provides judgment. The framework provides structure.

## 151. The Evidence-To-Answer Pipeline

The framework separates evidence gathering from answer writing into distinct nodes. After the executor finishes the plan, the run flows through fact extraction, synthesis, optional review, optional revision, and finalization. The shape is: planner, then the executor loop, then fact extractor, then synthesizer, then reviewer if warranted, then revision if requested, then finalizer.

The point of the separation is that the executor only orchestrates tools, deterministic extraction compresses evidence, one model call writes the answer, and the reviewer judges rather than rewrites. This keeps each model call small and removes the old failure where a revise verdict sent the run back into the tool loop.

## 152. Fact Extractor

The fact extractor is a deterministic node — no model call — that converts artifacts into small, source-linked facts. Downstream authoring nodes then reason over compact claims instead of raw tool payloads.

Deterministic extraction is a cost and stability optimization: compressing evidence into facts costs nothing, and the synthesizer and reviewer never have to carry large tool output.

## 153. Structured Fact Contract

Tools can return rich structure. The fact extractor prefers structured facts a tool supplies at known locations — a facts list, or facts nested under data, display, or metadata — and generic collections such as items, results, rows, panels, or tables, before falling back to splitting an artifact summary into lines.

For this to work end to end, truncation preserves a bounded copy of those recognized structured fields in the artifact's compact reference instead of reducing them to counts. The practical guidance: a tool that returns a large collection should expose it under one of these keys so the agent can extract it richly, rather than as a bare top-level list.

## 154. Synthesizer

The synthesizer is the single normal authoring pass. It writes one draft answer from facts only and tags it with a draft kind — model prose, a deterministic mechanical dump, or a passed-through executor draft. It emits an event on every path, including when it skips the model or falls back, so streaming always shows synthesis activity, and it decides whether the draft even needs review.

A single authoring call is the norm; the reviewer and revision run only when warranted.

## 155. Revision Node

The revision node applies exactly one bounded rewrite using the same facts and the reviewer's issues. It calls no tools, and there is deliberately no edge from it back to the executor. If the facts are insufficient, it is instructed to state the limitation rather than invent. This is what makes a revise verdict safe: it improves wording and grounding without reopening the tool loop.

## 156. Follow-Up Query Rewrite

On a follow-up turn, a bare question ("how many are there?") carries no nouns for semantic tool search. The planner is asked to emit a standalone, pronoun-resolved search query, which becomes the retrieval query the executor uses for tool discovery — so search matches on real nouns rather than pronouns.

The rewrite lives in the planner because the planner already runs once and already sees history, so it costs no extra model call. A deterministic fallback — prepending the most recent user turn on follow-ups — is used when the planner is disabled, and it is seeded into initial state so a retrieval query is always present. The literal user request is never overwritten, so the final answer still addresses what was actually asked.

## 157. In-Loop Memory Compaction (Running Summary)

For long investigations, evidence accumulates faster than either the model context or the run's memory should hold. Rather than blindly dropping low-scoring artifacts, the summarizer node compresses before it drops. When retained artifacts approach the cap, the executor loop detours through the summarizer, which makes one model call to fold the lower-scoring artifacts into a compact running summary, keeps the highest-scoring artifacts intact, and returns to the executor with freed context.

The running summary is injected high in the executor's context and seeded into the fact extractor, so evidence that was summarized away still reaches the answer. The feature is optional and bounded three ways: a hard cycle cap, a keep-count clamped below the trigger so compaction always makes progress, and a deterministic fallback memo if the model call times out.

## 158. Provenance Sidecar

Citations must survive compaction. Alongside the prose running summary, the summarizer keeps a structured sidecar recording each folded artifact's identifier, tool, and source reference. This is independent of the memo text, so it cannot be mangled by the model.

Two mechanisms then complement each other: the memo carries inline source markers keyed by artifact identifier for the model to cite in prose, and the sidecar gives the finalizer structured references to cite when grounding is enforced — so a citation can survive even a fully compacted run.

## 159. Execution Memory After Compaction

Because the summarizer drops artifacts, the executor cannot rely on artifacts alone to remember which tools already ran for a step. Duplicate-tool prevention and required-tool checks therefore read both artifacts and tool-call records, and tool-call records carry their plan-step and replan identifiers and are not dropped by compaction. This keeps loop control correct even after aggressive memory compaction.

## 160. Exactly-Once Terminal Event

Several nodes set the done phase as a routing signal, but only the finalizer should emit the terminal done event. The event mapper is told which node produced each update and emits done only for the finalizer's update, so hosts and callbacks never see duplicate or premature terminal events. Every terminal path is routed through the finalizer for this reason, and any unexpected phase is also routed there so a run never ends on an empty response.
