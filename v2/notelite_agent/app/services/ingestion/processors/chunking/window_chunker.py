from app.core.config import CHUNK_OVERLAP, MAX_CHUNK_SIZE


class WindowChunker:
    """Final hard-size splitter with overlap."""

    def split(self, text: str) -> list[str]:
        clean = text.strip()
        if not clean:
            return []
        if len(clean) <= MAX_CHUNK_SIZE:
            return [clean]

        overlap = max(0, min(CHUNK_OVERLAP, max(0, MAX_CHUNK_SIZE - 1)))
        step = max(1, MAX_CHUNK_SIZE - overlap)

        parts = []
        start = 0
        while start < len(clean):
            end = min(start + MAX_CHUNK_SIZE, len(clean))
            if end < len(clean):
                cut = clean.rfind(" ", start + int(MAX_CHUNK_SIZE * 0.6), end)
                if cut > start:
                    end = cut

            piece = clean[start:end].strip()
            if piece:
                parts.append(piece)

            if end >= len(clean):
                break

            next_start = self._align_start_to_word_boundary(clean, end - overlap)
            if next_start <= start:
                next_start = self._align_start_to_word_boundary(clean, start + step)
            start = next_start

        return parts

    @staticmethod
    def _align_start_to_word_boundary(text: str, start: int) -> int:
        """Move a window start out of the middle of a word."""
        start = max(0, min(start, len(text)))
        if start == 0 or start >= len(text):
            return start

        if text[start].isspace():
            while start < len(text) and text[start].isspace():
                start += 1
            return start

        if text[start - 1].isspace():
            return start

        next_space = text.find(" ", start)
        if next_space == -1:
            return start

        return next_space + 1
