Here is the problem and what to fix, in order.

---

## What’s wrong today

The pipeline is **one-way**: gather tools → extract facts → write answer → review → maybe rewrite text → done.

Once the executor hands off to `fact_extractor`, **no node can call more tools**. So when the reviewer says “you’re missing evidence” (e.g. need `get_panel_data`, not `run_search`), the system only goes to **revision** — which rewrites the draft from the **same** facts. It cannot go get new data.

That’s why you see bad answers, “tool already called,” and stale facts bleeding across questions.

---

## Step 1 — Teach the reviewer two kinds of “REVISE”

Today, every `REVISE` means: **fix the wording**.

You need a split:

- **Text revise** — answer is wrong/incomplete but facts are enough → go to **revision** (current behavior).
- **Evidence revise** — answer needs **more tool calls** (`missing_evidence` names a tool or gap) → go back to **executor**.

The reviewer already outputs `missing_evidence`. The fix is routing logic: if missing evidence implies a tool that wasn’t called (or failed), route to executor instead of revision.

---

## Step 2 — Add a graph path: reviewer → executor

Today in `graph.py`:

```
reviewer → revision → finalizer
```

You need:

```
reviewer → executor   (when more tools needed)
reviewer → revision   (when only rewrite needed)
reviewer → finalizer  (APPROVE / REJECT / limits)
```

After re-explore, the loop should continue normally:

```
executor → fact_extractor → synthesizer → reviewer → …
```

---

## Step 3 — Add state and caps for re-explore

Track something like `explore_cycles` or `re_explore_cycles` in `iteration`, with a config cap (e.g. 2).

Without a cap, reviewer ↔ executor could loop forever.

Also pass **reviewer feedback** into the executor prompt (“still need: get_panel_data for dashboard X”) so the next tool choice is guided, not a blind retry.

---

## Step 4 — Fix executor guards that block exploration

Two guards stop multi-step Splunk work:

1. **Duplicate tool skip** — same tool name on the same plan step → forced `finish_step`.  
   Fix: allow the same tool again when **arguments differ** (e.g. second `get_panel_data` with different `panel_tokens`).

2. **`max_tool_calls_per_step`** (default 3) — fine for simple tasks, tight for “list dashboards → get dashboard → get panel data.”  
   Fix: raise for Splunk/exploration mode, or count re-explore as a new “exploration step” with a fresh per-step budget.

---

## Step 5 — Stop stale facts from polluting new questions

With `cross_turn_artifact_persistence: true`, old artifacts from a prior turn can feed `fact_extractor` on a new question (you saw 24 stale facts from one weak `run_search`).

Fix options (pick one or combine):

- Scope facts/artifacts to **current user query / turn**.
- Clear or downgrade cross-turn artifacts when the question changes.
- Or disable cross-turn persistence for Splunk unless you explicitly want session memory.

---

## Step 6 — Raise fact/evidence budgets for list-heavy tasks

`fact_extractor` caps facts at `max_artifacts_in_prompt × 3` (30 in `default.yaml`).  
32 dashboards → only ~12 show up because MCP emits many facts and the budget fills early.

Fix: higher `max_artifacts_in_prompt` / fact cap in `splunk.yaml` or Studio runtime overrides, and/or smarter fact ranking so list summaries aren’t dropped.

---

## Step 7 — MCP `run_search` (smaller, separate)

`run_search` returns rows but **no `facts[]`**, so grounding is weaker than dashboard tools.

Add lightweight aggregate facts: `row_count`, `truncated`, error message, SPL used — not one fact per row.

---

## Step 8 — Prompts and Studio config

Even with code fixes, the model must know:

- Splunk NL questions → `search_panels` / `get_dashboard` → **`get_panel_data`** with user **`panel_tokens`**, not raw `run_search` for dashboard metrics.
- When reviewer sends it back, call the **specific** missing tool.

Paste updated Splunk instructions into Studio `config.instructions` and ensure `list_panels`, `run_search`, `get_panel_data` are in the agent’s active tool allowlist.

---

## Step 9 — Tests

Add cases for:

- Reviewer `missing_evidence` → routes to executor, not revision.
- Re-explore capped at N cycles.
- Same tool, different args → allowed.
- New question does not reuse old artifacts when persistence is off/scoped.

---

## Mental model

| Today | After fix |
|--------|-----------|
| Reviewer finds gap → rewrite text | Reviewer finds gap → **go get data** |
| Executor runs once per plan step | Executor can **re-enter** after review |
| Duplicate tool = stop | Same tool, new args = **continue** |
| Facts from last turn bleed in | Facts scoped to **this question** |

**Bottom line:** the main fix is **reviewer-driven re-entry to executor** plus loosening the guards and budgets that currently force early stop. Revision stays for “words wrong”; executor re-entry is for “evidence missing.”