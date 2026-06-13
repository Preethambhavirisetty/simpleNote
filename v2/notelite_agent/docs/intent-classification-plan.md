## Intent Definitions and Retrieval Steps

**lookup**
User wants a specific fact or detail from a known or implied note.
```
"what did Ananya say about the promotion"
"what was the Qdrant p99 latency last quarter"
"what time is the next sync"
```
Steps:
```
1. Keep the original query and optionally generate a HyDE expansion
2. Dense search with original query + HyDE → notelite_chunks (top 50)
3. BM25 sparse search with original query → notelite_chunks (top 50)
4. RRF fusion → top 30
5. Rerank → top 5
6. Context assembly with prev/next expansion
7. LLM answer grounded in chunks
```

---

**search**
User wants to find notes or passages matching a theme, topic, or concept. Does not know which document contains it.
```
"find all notes about career stress"
"notes where I mentioned Rohan"
"anything I wrote about the EV startup idea"
```
Steps:
```
1. Keep the original query and optionally generate a HyDE expansion
2. Dense search → notelite_summaries and notelite_questions for candidate doc_ids
3. Search chunks within candidate doc_ids and run a smaller global chunk search in parallel
4. BM25 sparse search with the original query across candidate and global chunks
5. RRF fusion without discarding global-recall candidates
6. Rerank → top 5
7. Return chunks with doc titles and dates
```

---

**timeline**
User wants information ordered by time — either evolution of a topic or what happened when.
```
"how has my thinking about switching jobs changed over the year"
"what was I writing about in January"
"show me notes from the Goa trip period"
```
Steps:
```
1. Extract temporal signals from query (month, year, event name)
2. Metadata filter → notelite_chunks by date range if explicit
3. Dense search → notelite_summaries (top 15)
4. Sort results by document date ascending
5. Fetch chunk samples from each matched document
6. LLM synthesizes chronological narrative from samples
```

---

**summary**
User wants a summary of a specific document or the day's / week's notes.
```
"summarize my Goa trip notes"
"give me a TL;DR of yesterday's meeting"
"what is the weekly sync note about"
```
Steps:
```
1. Identify target document from query
   → entity match on document title or date
   → if ambiguous, ask user to clarify before retrieving
2. Fetch the pre-computed summary artifact by doc_id from the configured summary store
3. Return directly — no vector search or reranking after the document is resolved
4. If no pre-computed summary exists, fetch all chunks for that doc and summarize live
```

---

**comparison**
User wants to compare two things across notes — people, decisions, time periods, topics.
```
"how did my mood in January compare to March"
"what did Rohan think versus what Appa thought about the job"
"compare the Qdrant benchmarks from last quarter and this quarter"
```
Steps:
```
1. Extract the two comparison targets from query
2. Run two parallel retrievals — one per target
   → HyDE variant per target
   → Dense search → notelite_chunks per target (top 20 each)
3. RRF fusion within each set separately
4. Rerank each set → top 5 each
5. Assemble context with both sets clearly labelled
6. LLM generates structured comparison
```

---

**navigation**
User wants to find or open a specific document by name, date, or title. Not searching for content — searching for the document itself.
```
"open my June 6 meeting notes"
"find the note called Weekly Sync"
"show me last Thursday's journal entry"
```
Steps:
```
1. Extract document identifier — title, date, or both
2. PostgreSQL lookup by title match or date filter
   → fuzzy title match using pg_trgm
   → exact date match if date present
3. No vector search needed
4. Return document metadata + first chunk as preview
5. If no match, fall back to search intent
```

---

**conversation**
User request does not require retrieving personal notes.
```
"hello"
"thanks, that helped"
"rewrite this sentence to sound friendlier"
```
Steps:
```
1. Skip retrieval
2. Route directly to the conversational response path
```

---

## How to Classify Intent

**Use your local LLM with a structured prompt.** One call, fast, returns a single intent label.

Prompt structure:
```
System:
You are an intent classifier for a personal notes app.
Classify the user query into exactly one of these intents:
lookup, search, timeline, summary, comparison, navigation, conversation

Rules:
- lookup: specific fact from a note
- search: find notes by topic or theme  
- timeline: time-ordered or date-based queries
- summary: summarize a specific document
- comparison: compare two things across notes
- navigation: find or open a specific document by name or date
- conversation: request does not require retrieving personal notes

Return only a JSON object: {"intent": "<label>", "confidence": 0.0-1.0}
No explanation.

User query: "{query}"
```

**Confidence threshold:** application code independently defaults to `search` when confidence is below the configured threshold, the model returns an unknown label, parsing fails, or the classifier is unavailable. Model-reported confidence is useful telemetry but is not trusted without validation.

**Speed:** intent classification should complete in under 500ms on your local inference. It is a tiny structured output task. Use Mistral 7B here — faster than Llama 3 8B for classification.

---

## How to Test Intent Classification Accuracy

**Step 1 — Build a golden test set manually.**

Write 10-15 queries per intent. 60-90 queries total. Label each by hand. These are your ground truth.

```json
[
  {"query": "what did Ananya say about the promotion", "intent": "lookup"},
  {"query": "find notes about career stress", "intent": "search"},
  {"query": "how has my thinking changed over the year", "intent": "timeline"},
  {"query": "summarize my Goa trip", "intent": "summary"},
  {"query": "what did Rohan think vs Appa", "intent": "comparison"},
  {"query": "open June 6 meeting notes", "intent": "navigation"}
]
```

**Step 2 — Run classifier against golden set.**

```python
correct = 0
confused = {}  # tracks which intents get confused for which

for item in golden_set:
    predicted = classify_intent(item["query"])
    if predicted == item["intent"]:
        correct += 1
    else:
        confused[item["intent"]] = confused.get(item["intent"], [])
        confused[item["intent"]].append(predicted)

accuracy = correct / len(golden_set)
```

**Step 3 — Build a confusion matrix.**

Which intents are getting confused for each other? The most common confusions in a notes app:

```
lookup  ↔ search    (both retrieve content, differ by specificity)
summary ↔ search    ("find and summarize" queries)
timeline ↔ search   (temporal queries without explicit dates)
navigation ↔ lookup (very specific queries about a known doc)
```

**Step 4 — Improve on confused pairs.**

Add more examples of the confused pairs to your prompt as few-shot examples. Two or three examples per confused pair usually resolves the issue without any model fine-tuning.

```
# Add to system prompt as few-shot examples
Example 1:
Query: "what was I writing about in January"
Intent: timeline  ← not search, even though no explicit date range

Example 2:
Query: "find my note from the Goa trip"
Intent: navigation  ← not search, user knows the document exists
```

**Step 5 — Target accuracy.**

```
> 90% overall accuracy    → production ready
85-90%                    → acceptable, improve confused pairs
< 85%                     → prompt needs significant work
```

**Step 6 — Ongoing monitoring.**

Log every intent classification in production with the query and predicted intent. Once you have 500+ real user queries, review the logs and update your golden test set with real examples. Real user queries are always more diverse than hand-written test cases.

## Implemented Classifier Gate

The classifier is intentionally isolated from retrieval routing until live accuracy is verified.

```bash
PYTHONPATH=. .venv/bin/python -m app.services.chat.intent_evaluation \
  app/services/tests/chat/intent_golden_set.yaml --minimum-accuracy 0.9
```

The command exits with code `0` only when live accuracy reaches the target, `1` when accuracy is below target, and `2` when the classifier endpoint is unavailable.


### Replayable Action

Intent classification is exposed as an isolated action and does not run retrieval:

```json
{
  "action_name": "retrieval.intent",
  "payload": {"query": "compare my January and March notes"}
}
```

The result includes `intent`, `confidence`, `raw_intent`, `used_fallback`, and `reason` so classification and fallback behavior can be inspected before routing is implemented.
