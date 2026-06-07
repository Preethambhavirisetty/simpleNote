from __future__ import annotations

import re

from app.services.ingestion.processors.chunking.semantic_chunker import SemanticChunker
from app.services.ingestion.processors.chunking.token_budget import within_chunk_budget
from app.services.ingestion.processors.chunking.validators import (
    is_heading_like,
    is_list_chunk,
    is_numbered_list_item,
    validate_chunk,
)

NUMBERED_HEADING_LINE_PATTERN = re.compile(
    r"^\s*(?P<prefix>(?:\d+(?:\.\d+)*)(?:\.)?)\s+(?P<title>.+)$"
)


class HeadingProcessor:
    """Processes heading-derived parts while preserving merge behavior."""

    def __init__(self, semantic_chunker: SemanticChunker):
        self.semantic_chunker = semantic_chunker

    def process(
        self,
        heading_parts: list[str],
        chunks: list[str],
        pending_paragraph: str,
        heading_context: list[str] | None = None,
    ) -> str:
        heading_context = heading_context if heading_context is not None else []
        pending_chunk = ""

        for index, part in enumerate(heading_parts):
            prev_part = heading_parts[index - 1] if index > 0 else ""
            next_part = heading_parts[index + 1] if index + 1 < len(heading_parts) else ""
            heading_line, depth = self._parse_numbered_heading(part, prev_part, next_part)

            candidate = f"{pending_chunk}\n{part}".strip() if pending_chunk else part

            if within_chunk_budget(candidate):
                pending_chunk = self._handle_candidate(candidate, chunks)
            else:
                if pending_chunk and validate_chunk(pending_chunk) == "VALID":
                    chunks.append(pending_chunk)
                if heading_line:
                    chunks.extend(
                        self._split_part_preserving_heading(
                            part,
                            heading_line,
                        )
                    )
                    pending_chunk = ""
                elif within_chunk_budget(part):
                    pending_chunk = self._handle_candidate(part, chunks)
                else:
                    chunks.extend(self.semantic_chunker.split(part))
                    pending_chunk = ""

            if heading_line:
                self._update_heading_context(heading_line, depth, heading_context)

        return self._flush_pending_chunk(pending_chunk, chunks, pending_paragraph)

    @staticmethod
    def _handle_candidate(candidate: str, chunks: list[str]) -> str:
        verdict = validate_chunk(candidate)
        if verdict == "DISCARD":
            return ""
        if verdict == "VALID":
            chunks.append(candidate)
            return ""
        return candidate

    @staticmethod
    def _parse_numbered_heading(
        part: str,
        prev_part: str,
        next_part: str,
    ) -> tuple[str | None, int]:
        if is_list_chunk(part):
            return None, 0

        if is_numbered_list_item(part):
            if is_numbered_list_item(prev_part) or is_numbered_list_item(next_part):
                return None, 0
            prev_text = prev_part.strip()
            if prev_text.endswith(":") or re.search(
                r"\b(?:step|steps|task|tasks|checklist|procedure|procedures|list|items?)\s*[:.]?$",
                prev_text,
                re.IGNORECASE,
            ):
                return None, 0

        first_line = part.splitlines()[0].strip()
        match = NUMBERED_HEADING_LINE_PATTERN.match(first_line)
        if not match:
            return None, 0

        prefix = match.group("prefix").rstrip(".")
        depth = len(prefix.split(".")) if prefix else 0
        return first_line, depth


    @staticmethod
    def _heading_context(heading_context: list[str], depth: int) -> str:
        return "\n".join(h for h in heading_context[:depth] if h)

    @staticmethod
    def _update_heading_context(
        heading_line: str,
        depth: int,
        heading_context: list[str],
    ) -> None:
        if depth <= len(heading_context):
            heading_context[depth - 1] = heading_line
            del heading_context[depth:]
            return

        while len(heading_context) < depth - 1:
            heading_context.append("")
        heading_context.append(heading_line)

    def _split_part_preserving_heading(
        self,
        part: str,
        heading_line: str,
    ) -> list[str]:
        parts = self.semantic_chunker.split(part)
        output = []
        for chunk in parts:
            first_line = chunk.splitlines()[0].strip() if chunk.strip() else ""
            if first_line == heading_line:
                output.append(chunk)
            else:
                output.append(f"{heading_line}\n{chunk}".strip())
        return output

    @staticmethod
    def _flush_pending_chunk(
        pending_chunk: str,
        chunks: list[str],
        pending_paragraph: str,
    ) -> str:
        if not pending_chunk:
            return pending_paragraph

        verdict = validate_chunk(pending_chunk)
        if verdict == "VALID":
            if is_heading_like(pending_chunk):
                return (
                    f"{pending_paragraph}\n{pending_chunk}".strip()
                    if pending_paragraph
                    else pending_chunk
                )
            chunks.append(pending_chunk)
        elif verdict == "NEEDS_MERGE":
            return (
                f"{pending_paragraph}\n{pending_chunk}".strip()
                if pending_paragraph
                else pending_chunk
            )

        return pending_paragraph
