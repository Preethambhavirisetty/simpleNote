import re

from app.core.config import CHUNK_OVERLAP, MAX_CHUNK_SIZE


_sentencizer = None


class WindowChunker:
    """Final size splitter using sentence-aware windows with overlap."""

    def split(self, text: str) -> list[str]:
        clean = text.strip()
        if not clean:
            return []
        if len(clean) <= MAX_CHUNK_SIZE:
            return [clean]

        sentences = self._split_sentences(clean)
        if len(sentences) <= 1:
            return self._hard_split(clean)

        parts = self._merge_sentence_windows(sentences)
        if any(len(part) > MAX_CHUNK_SIZE for part in parts):
            bounded_parts = []
            for part in parts:
                bounded_parts.extend(self._hard_split(part))
            return bounded_parts

        return parts

    def _merge_sentence_windows(self, sentences: list[str]) -> list[str]:
        parts = []
        current = []
        current_len = 0

        for sentence in sentences:
            sentence_len = len(sentence)
            separator_len = 1 if current else 0

            if current and current_len + separator_len + sentence_len > MAX_CHUNK_SIZE:
                parts.append(" ".join(current).strip())
                current = self._overlap_sentences(current)
                current_len = len(" ".join(current))

            if not current:
                current = [sentence]
                current_len = sentence_len
            elif current_len + 1 + sentence_len <= MAX_CHUNK_SIZE:
                current.append(sentence)
                current_len += 1 + sentence_len
            else:
                if sentence_len <= MAX_CHUNK_SIZE:
                    current = [sentence]
                    current_len = sentence_len
                else:
                    parts.extend(self._hard_split(sentence))
                    current = []
                    current_len = 0

        if current:
            parts.append(" ".join(current).strip())

        return [part for part in parts if part]

    @staticmethod
    def _overlap_sentences(sentences: list[str]) -> list[str]:
        if not sentences or CHUNK_OVERLAP <= 0:
            return []

        overlap = []
        total_len = 0
        for sentence in reversed(sentences):
            next_len = len(sentence) + (1 if overlap else 0)
            if overlap and total_len + next_len > CHUNK_OVERLAP:
                break
            overlap.insert(0, sentence)
            total_len += next_len

        return overlap[-1:] if not overlap else overlap

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        nlp = _get_sentencizer()
        if nlp is not None:
            doc = nlp(text)
            sentences = [sent.text.strip() for sent in doc.sents if sent.text.strip()]
            if sentences:
                return sentences

        return [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", text)
            if sentence.strip()
        ]

    def _hard_split(self, text: str) -> list[str]:
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


def _get_sentencizer():
    global _sentencizer
    if _sentencizer is None:
        try:
            import spacy

            _sentencizer = spacy.blank("en")
            _sentencizer.add_pipe("sentencizer")
        except Exception:
            _sentencizer = False

    return _sentencizer if _sentencizer is not False else None
