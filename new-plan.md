Updated plan, keeping MCP-side rich extractors as the preferred future direction, but **out of scope for now**.

**Phase 1: Workflow-Side Generic Fact Contract**
1. Update `fact_extractor` to prefer structured facts if present in tool artifacts:
   - `artifact.raw_ref.facts`
   - `artifact.raw_ref.data.facts`
   - `artifact.raw_ref.display.facts`
   - `artifact.raw_ref.metadata.facts`
2. Normalize those facts into `Fact` state objects.
3. Keep current line-splitting as fallback.
4. Add generic support for structured tables/lists if present:
   - `display.tables`
   - `items`
   - `results`
   - `rows`
   - `panels`
   
This avoids app coupling while letting future MCP tools provide richer facts.

**Phase 2: Evidence Fidelity Defaults**
5. Keep `default.yaml` moderate for generic apps.
6. Add comments/docs showing app-specific override recommendations:
   - dashboards/reports: `max_artifact_chars: 12000-20000`
   - high-volume tables: increase `max_list_rows_visible`
   - quick chat tools: keep default lower
7. Do not bake Splunk-specific budgets into the generic default.

**Phase 3: Reviewer Robustness**
8. Make reviewer parsing:
   - JSON first
   - markdown fallback with `parse_review_markdown`
   - safe `REVISE` fallback with `reviewer.parse_failed` event
9. Keep reviewer judge-only.
10. Do not reintroduce reviewer-to-executor loops.

**Phase 4: Telemetry / Activity Cleanup**
11. Emit synthesizer events for all paths:
   - `synthesizer.completed`
   - `synthesizer.skipped`
   - `synthesizer.fallback`
   - `synthesizer.timeout`
12. Add missing SSE activity fields:
   - `fact_count`
   - `handoff`
   - `answer_chars`
   - `revision_cycles`
   - `truncated_source_count`
13. Keep UI events clean and debug trace detailed.

**Phase 5: Config Honesty**
14. Fix `draft_kind` comment to include `"executor_draft"`.
15. Remove/deprecate dead `reject_action: replan` behavior from docs/config expectations.
16. Keep `reject_action: abort` as the honest current behavior.
17. Unknown graph phase should produce a safe finalizer/error event instead of silently ending.

**Phase 6: Tests**
18. Add tests for structured facts in artifacts.
19. Add tests for generic table/list extraction fallback.
20. Add reviewer JSON/markdown/failure parsing tests.
21. Add synthesizer skipped/fallback event tests.
22. Add golden-path graph test for:
```text
planner -> executor -> fact_extractor -> synthesizer -> reviewer/finalizer
```
23. Add revise-path graph test:
```text
reviewer -> revision -> finalizer
```

This keeps the workflow service generic now, while preparing it to benefit from richer MCP output later without another architecture change.