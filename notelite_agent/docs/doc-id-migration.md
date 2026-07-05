# One-time cleanup: document id format change

The agent's document identity changed from `{user_id}-{folder_id}-{note_id}` to
`{user_id}-{note_id}` (folder membership is mutable metadata, not identity — the old
format orphaned a note's vectors every time it moved between folders).

The change is applied in `IngestionOrchestrator._doc_id` and
`PipelineActionService._doc_id`. New and re-ingested notes use the new id
automatically. Documents indexed **before** this change still exist under old-format
ids and are never targeted by upserts or deletes again, so they must be cleaned up
once per environment.

## What is affected

- Qdrant points in the chunk, `_summaries`, and `_questions` collections whose
  `doc_id` payload has the old three-UUID format.
- `agent_documents` rows keyed by old-format `doc_id` (deleting these cascades to
  `agent_chunk_dates` and `agent_skipped_chunks`).

Old- and new-format ids are easy to tell apart: three joined UUIDs are 110
characters, two are 73.

## Procedure (in this order)

1. **Deploy** the identity change (agent API + agent-celery worker together, since
   both embed the formula).
2. **Re-ingest every note** so each one exists under its new id. From the backend
   container, enqueue an upsert per note through the existing ingestion task — the
   same payload `NoteService._ingestion_payload` builds. The version guard makes
   this safe to re-run (equal versions are not stale).
3. **Delete old-format artifacts** only after step 2 completes:
   - Qdrant: for each of the three collections, delete points where
     `len(payload["doc_id"]) > 73` (scroll + delete by ids, or a filtered delete if
     a `doc_id` length index is impractical — total point counts are small enough
     to scroll).
   - Postgres: `DELETE FROM agent_documents WHERE length(doc_id) > 73;`

Until step 3 runs, retrieval may return duplicate chunks for notes that were
re-ingested (one old-format copy, one new). Running step 3 *before* step 2 would
instead make not-yet-re-ingested notes temporarily disappear from retrieval —
prefer duplicates over gaps, hence the order above.

Fresh environments (empty collections) need no action.
