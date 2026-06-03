import re

from app.services.ingestion.processors.chunking.patterns import (
    HEADING_PATTERN,
    NUMBERED_LINE_PATTERN,
)
from app.services.ingestion.processors.chunking.validators import (
    is_inside_fenced_code,
    is_numbered_list_item,
)


class HeadingChunker:
    """Paragraph and heading-oriented splitting helpers."""

    NUMBERED_LIST_LINE_PATTERN = re.compile(r"^\s*\d+[.)]\s+")
    LIST_INTRO_PATTERN = re.compile(
        r"\b(?:step|steps|task|tasks|checklist|procedure|procedures|list|items?)\s*[:.]?$",
        re.IGNORECASE,
    )

    def split(self, text: str) -> list[str]:
        parts = []
        start = 0

        for match in HEADING_PATTERN.finditer(text):
            if is_inside_fenced_code(text, match.start()):
                continue

            prev_line = ""
            if start < match.start():
                prev_lines = text[: match.start()].splitlines()
                if prev_lines:
                    prev_line = prev_lines[-1].strip()

            next_line_end = text.find("\n", match.start() + 1)
            next_line = (
                text[match.start() + 1 : next_line_end].strip()
                if next_line_end != -1
                else text[match.start() + 1 :].strip()
            )

            if self.NUMBERED_LIST_LINE_PATTERN.match(next_line) and (
                self.NUMBERED_LIST_LINE_PATTERN.match(prev_line)
                or prev_line.endswith(":")
                or self.LIST_INTRO_PATTERN.search(prev_line)
            ):
                continue

            part = text[start:match.start()].strip()
            if part:
                parts.append(part)
            start = match.start()

        remainder = text[start:].strip()
        if remainder:
            parts.append(remainder)

        return parts

    def inject_numbered_line_breaks(self, text: str) -> str:
        lines = text.splitlines()
        output = []
        in_code = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("```"):
                in_code = not in_code
                output.append(line)
                continue

            if in_code:
                output.append(line)
                continue

            if NUMBERED_LINE_PATTERN.match(line) and output and output[-1].strip():
                prev_line = output[-1].strip()
                if (
                    self.NUMBERED_LIST_LINE_PATTERN.match(line)
                    and self.NUMBERED_LIST_LINE_PATTERN.match(prev_line)
                ):
                    output.append(line)
                    continue
                output.append("")
            output.append(line)

        return "\n".join(output)
