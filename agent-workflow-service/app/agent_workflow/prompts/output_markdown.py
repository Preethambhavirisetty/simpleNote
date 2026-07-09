"""Shared user-facing markdown rules for answer-producing nodes."""

MARKDOWN_OUTPUT_RULES = """
## User-facing Markdown

When writing an answer for the user (not JSON, not internal notes):

- Return GitHub-flavored Markdown only. No HTML. Do not wrap the entire answer in a code fence.
- Start with a `##` heading that summarizes the answer.
- Put a blank line before headings and before lists.
- Use bullet lists for enumerations.
- Use GFM tables when presenting 3+ comparable rows with shared columns.
- Use fenced code blocks with a language tag for SPL, SQL, shell, or JSON snippets.
- Cite sources inline from facts, e.g. `(source: doc_id/page)` or the tool name in backticks.
- Do not mention internal nodes, review, planner, or policy.
""".strip()
