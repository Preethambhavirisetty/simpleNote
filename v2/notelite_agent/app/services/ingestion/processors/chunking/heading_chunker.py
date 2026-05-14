from app.services.ingestion.processors.chunking.patterns import (
    HEADING_PATTERN,
    NUMBERED_LINE_PATTERN,
)


class HeadingChunker:
    """Paragraph and heading-oriented splitting helpers."""

    def split(self, text: str) -> list[str]:
        parts = HEADING_PATTERN.split(text)
        return [part.strip() for part in parts if part.strip()]

    def inject_numbered_line_breaks(self, text: str) -> str:
        lines = text.splitlines()
        output = []

        for line in lines:
            if NUMBERED_LINE_PATTERN.match(line) and output and output[-1].strip():
                output.append("")
            output.append(line)

        return "\n".join(output)
