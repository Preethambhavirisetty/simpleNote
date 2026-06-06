## content
Default type. Assign when no other type matches. Prose sentences, narrative text, descriptions, explanations. Should never contain a heading as the only text. If a heading has body text beneath it, the body is `content` and the heading either merges with it or becomes `heading_only`.

## heading_only
Assign when a chunk contains only heading lines with no body text beneath any of them. Multiple consecutive empty headings collapse into one `heading_only` chunk. The moment any heading has even one sentence of body text, that section becomes `content`, not `heading_only`.

## table
Assign when the chunk is dominated by pipe-delimited rows. Detect by counting pipe characters per line — if most lines have 2+ pipes, it's a table. Works with or without the markdown `|---|` separator row. A single prose sentence introducing the table belongs in a separate `content` chunk before it. A single prose sentence after belongs in a separate `content` chunk after it.

## code
Assign when content is wrapped in triple backtick fences regardless of language tag. Also assign for unfenced command sequences — detect by looking for lines that start with shell commands (`python`, `pip`, `npm`, `docker`, `git`, `curl`, `cd`, `source`, `export`, `./`) or are clearly code syntax (assignments, function definitions, indented blocks). Keep the entire sequence as one atomic chunk. Never split inside a code block.

## json
Assign when content is a valid or near-valid JSON structure — starts with `{` or `[` and ends with `}` or `]` with key-value pairs inside. Do not assign to `[Reserved for future use]` or similar — require at least one quoted key or colon-separated pair inside the braces to confirm. When JSON appears inside a fenced block, still type as `json` not `code`.

## faq
Assign when content contains one or more Q/A pairs. Detect by lines starting with `Q:` or `Question:` followed by lines starting with `A:` or `Answer:`. Keep all Q/A pairs in the same chunk regardless of answer length — do not split a FAQ chunk mid-pair just because an answer is long. A section heading like `Frequently Asked Questions` can stay in the same chunk.

## transcript
Assign when content shows alternating speaker turns. Detect by lines matching `Name:` or `Name\n` followed by dialogue, OR timestamped formats like `[HH:MM]` or `HH:MM AM/PM` on a line followed by a speaker name. The key signal is at least two distinct speaker labels appearing in alternation. If a transcript contains an embedded code block, split the code out as a separate `code` chunk and keep the surrounding turns as `transcript`.

## quote
Assign when content consists of one or more quoted statements. Detect by lines wrapped in double quotes, or lines starting with `>` markdown blockquote syntax. Attribution lines starting with `—` or `–` after a quoted line belong in the same `quote` chunk — do not let the attribution line break the quote detection or trigger a different type.

## glossary
Assign when content contains definition pairs — a term followed by its definition, separated by colon, dash, or em dash. Formats include `TERM: definition`, `TERM — definition`, or `Term\n  definition`. All entries in a glossary block stay in one chunk regardless of definition length. If individual definitions are long paragraphs, do not split mid-definition.

## contact
Assign ONLY when content contains at least one of: email address pattern (`x@x.x`), phone number pattern, or explicit label like `Email:` / `Phone:` / `Tel:`. A name alone is not enough. URLs alone are not enough. Identifiers alone (`INC-2024-001`) are not enough. All-caps text is not enough. This type has the tightest entry requirement — false positives here corrupt everything downstream.

## address
Assign when content matches the pattern of a physical mailing address — a street number and name followed by a city/state/zip or city/country combination. International formats (German, Japanese, UK) qualify. A name on the first line is fine. Distinguish from `contact` — an address with no email or phone is `address`, not `contact`. An address combined with email or phone is `contact`.

## footer
Assign when content consists of page markers, copyright lines, confidentiality notices, or repeated boilerplate with no informational content. Detection signals: `Page X of Y`, `CONFIDENTIAL`, `© YEAR`, `Internal Use Only`, `Generated on`, or any line repeated 3+ times identically. Standalone repeated boilerplate with no surrounding content is `footer`. When footer text is embedded mid-chunk between real content paragraphs, split it out as its own `footer` chunk rather than typing the whole chunk as `footer`.

## structured_list
Assign when content is a numbered or lettered list — arabic numerals (`1. 2. 3.`), hierarchical decimals (`1.1 1.2`), alphabetic (`A. B. C.`), or roman numerals (`i. ii.` or `I. II.`). Mixed formats in the same block stay as one `structured_list` chunk. Distinguish from `list` — `structured_list` has explicit ordering markers, `list` uses unordered bullets.

## list
Assign when content is an unordered bullet list using `-`, `*`, or `+` as markers. Nested lists stay as one `list` chunk — do not split at indentation levels. Task lists with `[ ]` and `[x]` markers are `list` not `structured_list`. If a list appears inside a larger mixed document, it may be split into its own `list` chunk when preceded or followed by prose.