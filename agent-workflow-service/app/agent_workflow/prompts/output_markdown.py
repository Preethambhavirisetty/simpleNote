"""Shared user-facing markdown rules for answer-producing nodes."""

MARKDOWN_OUTPUT_RULES = """
## User-facing Markdown

When writing an answer for the user (not JSON, not internal notes):

- Return GitHub-flavored Markdown only. No HTML. Do not wrap the entire answer in a code fence.
- Write like a helpful colleague, not a report template. Use plain language.
- **Answer first.** Open with 1–2 sentences that directly answer the question (yes/no, count, list summary, recommendation).
- Put supporting detail after the answer: a short table, bullets, or one compact paragraph.
- Put source/context last in a muted-style line, e.g. a final `### Details` or one line: `Source: dashboard_name · filters applied`.
- Do not use robotic section headers like "Dashboard Used", "Filters Applied", "Supporting Evidence" unless the user asked for a formal report.
- Do not tell the user to apply filters in a dashboard UI. If filters are needed, the workflow should run tools — say what you tried instead.
- Use a `##` heading only when the answer is long; for short answers, lead with the conclusion and skip the heading.
- Put a blank line before headings, lists, and tables.
- Use bullet lists for short enumerations (≤5 items).
- Use GFM tables when presenting 2–5 comparable rows with shared columns. Never dump full tool output.
- Use fenced code blocks with a language tag only for SPL, SQL, shell, or JSON snippets the user needs.
- Cite sources briefly at the end, not inline on every sentence. One source line is enough.
- Do not mention internal nodes, review, planner, MCP, or policy.
- If evidence is incomplete, say so plainly and ask one focused clarification question — or state what tool step is still needed.
""".strip()
