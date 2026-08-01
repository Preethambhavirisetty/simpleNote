# Agent Workflow Service — End-to-End Architecture Diagrams

Companion to `ARCHITECTURE.md` and `AGENT-WORKFLOW.md`. Three views: the request
lifecycle (routing ladder + teardown), the LangGraph state machine with the
executor's guard stack, and the component/store topology.

## 1. Request lifecycle — routing ladder and turn teardown

Each tier decides only if the tier above didn't. Every terminal path runs the
same finalize sequence.

```mermaid
flowchart TD
    A[HTTP API<br/>run / stream / runtime-bundle / resume] --> B[AgentEngine<br/>validate request · begin trace · HEC run.started]

    B --> T0{Tier 0<br/>fast path?<br/>deterministic: greeting, math}
    T0 -- yes --> FP[Direct LLM answer<br/>identity + memory aware, no tools, no graph]
    T0 -- no --> PS[_prepare_session<br/>load conversation memory once<br/>resolve follow-up policy<br/>regex + memory-entity overlap<br/>artifact persistence OFF — memory-first]

    PS --> MC{new topic?}
    MC -- yes --> CLR[clear conversation memory<br/>HEC memory.cleared]
    MC -- no --> DP
    CLR --> DP{deterministic playbook<br/>matches? claim class + topics}
    DP -- yes --> GP[Route = complex<br/>planner installs YAML recipe steps<br/>+ evidence_required contract]
    DP -- no --> T3[LLM route classifier<br/>semantic tool pre-search →<br/>question + history + memory entities<br/>+ tool candidates + config playbooks]

    T3 -- direct<br/>identity/meta, never when require_tools --> DR[Direct answer from identity + manifest + memory<br/>no graph, no tools]
    T3 -- simple --> G1[Graph at executor<br/>single-step plan · tight budgets · reviewer skipped]
    T3 -- playbook --> G2[Graph at executor<br/>config playbook steps ARE the plan · full pipeline]
    T3 -- complex / fallback --> G3[Graph at planner<br/>full deep pipeline]
    T3 -. deep mode ON: only complex/playbook offered .- T3

    GP --> GR[LangGraph run]
    G1 --> GR
    G2 --> GR
    G3 --> GR

    GR --> FIN[Turn teardown — every terminal path<br/>extract memory slots → save → HEC memory.updated<br/>cleanup checkpoint thread · HEC run.completed]
    FP --> FIN
    DR --> FIN
```

## 2. The graph and the executor guard stack

```mermaid
flowchart TD
    START((START)) -->|phase=planning| PL[planner<br/>LLM plan + standalone query rewrite]
    START -->|phase=executing<br/>simple / playbook / planner-off| EX
    START -->|phase=fact_extracting<br/>follow-up reuse| FE

    PL --> EX[executor]
    subgraph EXG[executor guard stack — every turn]
        direction TB
        g1[action recovery: tool-name-as-action → call_tool<br/>unknown action → guidance retry]
        g2[argument injection from runtime context]
        g3[deterministic argument repair:<br/>prior call args → memory slots → unique result field]
        g4[duplicate-call + invalid-call dedup by signature]
        g5[route + per-step budgets · schema validation]
        g6[finish/draft vetoes: required tools, stop condition,<br/>follow-up recall — with deadlock-break arbitration]
        g7[guidance loop: every veto/error becomes<br/>a correction in the next prompt]
    end
    EX --- EXG

    EX -->|destructive tool| AP[approval<br/>human-in-the-loop interrupt<br/>pause / resume via checkpoint]
    AP --> EX
    EX -->|memory pressure| SU[summarizer<br/>compact artifacts → running summary]
    SU --> EX
    EX -->|evidence ready / budgets / no-progress stop| FE[fact_extractor<br/>deterministic · fair per-artifact quota<br/>+ call-provenance facts]
    FE --> SY[synthesizer<br/>primary evidence verbatim + facts index<br/>+ follow-up history + memory entities<br/>row-evidence guard by claim class]
    SY -->|reviewing| RV[reviewer<br/>LLM verdict + deterministic gates:<br/>claim-class row gates · draft/threshold consistency ·<br/>config discovery priorities · contradiction/format checks]
    SY -->|reviewer skipped: simple route / on_risk clean| FZ

    RV -->|APPROVE| FZ[finalizer]
    RV -->|REVISE/REJECT + missing evidence<br/>bounded re-explore, fresh budget| EX
    RV -->|REVISE wording| RW[revision<br/>same facts · unverified-items honesty contract]
    RW --> FZ
    FZ --> END((END))
```

## 3. Components and stores

```mermaid
flowchart LR
    subgraph API[app/api]
        RT[runtime endpoints + SSE adapter<br/>activity-field whitelist]
        AC[action controller<br/>per-stage testing]
    end

    subgraph CORE[app/agent_workflow]
        EN[engine<br/>routing ladder · turn teardown · caches]
        RO[router.py<br/>route classifier + identity fallback]
        GRAPH[graph.py — LangGraph nodes]
        CB[context builder<br/>priority-budgeted prompt sections]
        EG[evidence_grade<br/>claim classes + row gates]
        FU[follow_up.py<br/>detection + recall policy]
        CMEM[conversation_memory<br/>slot store + extraction]
        AST[artifact_store<br/>cross-turn evidence]
        HEC[splunk_hec<br/>async background sink]
    end

    subgraph EXT[external]
        LLM[(LLM provider<br/>v2 inference / OpenAI-compatible)]
        MCP[(MCP servers<br/>tools)]
        TIX[(semantic tool index)]
        RD[(Redis<br/>artifacts + memory<br/>in-proc fallback)]
        SPL[(Splunk HEC)]
        CKPT[(checkpointer<br/>memory / postgres)]
    end

    RT --> EN
    AC --> CORE
    EN --> RO --> LLM
    EN --> GRAPH
    GRAPH --> CB --> LLM
    GRAPH --> MCP
    RO --> TIX
    GRAPH --> TIX
    EN --> CMEM --> RD
    EN --> AST --> RD
    EN --> HEC --> SPL
    GRAPH --> EG
    EN --> FU
    GRAPH --> CKPT
```

## Reading guide

- **Configuration is the app boundary**: playbooks, identity, instructions,
  discovery priorities, tool policies, budgets, and profiles are all config;
  framework code stays application-agnostic.
- **Trust ladder**: deterministic checks run before LLM judgment at every
  layer (fast path before router; guards before model retries; deterministic
  gates before the reviewer LLM).
- **Every loop has a bounded escape**: iteration caps, no-progress stall stop,
  deadlock-break arbitration, re-explore/review/revision cycle caps, and the
  recursion budget sized from all of them.
- **Evidence requirement flows from config, not regex**: a deterministic
  playbook declares its claim class and stamps `evidence_required` on the plan;
  the row-level gate keys off that plan contract, and the regex claim classifier
  is only the fallback for un-playbooked runs.
- **Continuity is memory-first**: conversation memory carries what the
  conversation established (active entity, collection, output shape — with
  superseded-value history), not raw prior-turn artifacts, which is the right
  granularity for follow-ups.
