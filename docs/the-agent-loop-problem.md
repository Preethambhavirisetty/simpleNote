Yes, this is a classic agent-loop problem: the agent is treating each step like a fresh attempt instead of maintaining a working memory of “what I already know, what failed, what tool options exist, and what I still need.”

To improve it, I’d focus on five things.

**1. Keep Tool Discovery Persistent**
If semantic tool search returns 7 tools, that result should not disappear after one failed tool call.

The agent state should retain something like:

```json
{
  "available_tools": [...],
  "tool_discovery_query": "...",
  "tool_attempts": [
    {
      "tool": "search_notes",
      "args": {...},
      "outcome": "no_relevant_results",
      "lesson": "Query was too broad; try folder/note discovery next."
    }
  ]
}
```

Then the next reasoning step should see:
- tools already discovered
- tools already tried
- why they failed
- which tools remain promising

Otherwise it keeps rediscovering the same tools and incorrectly concludes the tool does not exist.

**2. Separate “Search For Tools” From “Use Tools”**
Tool discovery should happen once at the beginning, or only when the existing catalog is insufficient.

A good rule:

```text
Do not run semantic_tool_search again unless:
- no known tool can satisfy the next step, or
- the user asks for a new capability outside the current tool set.
```

For your case, the agent should discover:

```text
search_notes
locate_notes
summarize_notes
list_notes
list_folders
```

Then reason over those tools directly.

**3. Add A Scratchpad / Working Memory**
The agent needs an iterative scratchpad that survives across steps:

```text
Goal:
Answer the user's question about X.

Known facts:
- User asked about ...
- search_notes returned no direct match for ...
- locate_notes found note A and note B.
- summarize_notes says note A contains ...

Open questions:
- Need exact detail Y.
- Need source/citation.

Next action:
Call summarize_notes on note A and B.
```

This should be injected into every executor turn. Without this, each turn is amnesiac.

**4. Teach Recovery From Bad Results**
“No relevant result” should not mean “tool missing.” It should mean “revise the retrieval strategy.”

For note/RAG workflows, recovery policy should be explicit:

```text
If search_notes returns weak/no results:
1. Try locate_notes with broader terms.
2. Try list_folders to understand workspace structure.
3. Try list_notes with search/filter.
4. Summarize likely notes.
5. Only then say the answer was not found.
```

This gives the agent a ladder instead of a cliff.

**5. Use Multi-Step Task Decomposition**
For questions needing extraction, the agent should not jump directly to the final tool. It should do:

```text
1. Understand the user’s requested entity/detail.
2. Find candidate notes/folders.
3. Extract relevant snippets/summaries.
4. Verify whether the extracted details answer the question.
5. Call the final expected tool/action with the extracted details.
6. Produce final answer with evidence.
```

In your `agent-workflow-service`, this likely means improving the executor prompt and state retention more than adding more tools.

A strong executor instruction would be:

```text
You are solving a multi-step task. Maintain a running working memory.

Before each tool call:
- State what you know.
- State what is still missing.
- Choose from known tools before rediscovering tools.

If a tool returns no relevant results:
- Do not conclude the tool does not exist.
- Record the failed query.
- Try a broader, narrower, or adjacent retrieval tool.
- Continue until the task is answered or all reasonable retrieval paths are exhausted.
```

**Most Important Fix**
Persist and re-inject these three things into every loop iteration:

```text
1. discovered tools
2. previous tool calls/results/failures
3. working memory / open questions
```

Your current failure sounds like the loop is pruning too aggressively: results and candidate tools are erased, so the agent loses continuity. For a real agent framework, tool discovery and intermediate findings should be summarized, compressed, and retained, not dropped.