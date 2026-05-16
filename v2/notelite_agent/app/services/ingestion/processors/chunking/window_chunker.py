import re

from app.core.config import CHUNK_OVERLAP, MAX_CHUNK_SIZE
from app.services.ingestion.processors.chunking.token_budget import (
    split_by_token_window,
    token_count,
    within_chunk_budget,
)


_sentencizer = None


class WindowChunker:
    """Final size splitter using sentence-aware windows with overlap."""

    def split(self, text: str) -> list[str]:
        clean = text.strip()
        if not clean:
            return []
        if within_chunk_budget(clean):
            return [clean]

        sentences = self._split_sentences(clean)
        if len(sentences) <= 1:
            return self._hard_split(clean)

        parts = self._merge_sentence_windows(sentences)
        if any(not within_chunk_budget(part) for part in parts):
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
            sentence_len = token_count(sentence)
            separator_len = 1 if current else 0

            if current and current_len + separator_len + sentence_len > MAX_CHUNK_SIZE:
                parts.append(" ".join(current).strip())
                current = self._overlap_sentences(current)
                current_len = token_count(" ".join(current)) if current else 0

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
            next_len = token_count(sentence) + (1 if overlap else 0)
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
        if within_chunk_budget(clean):
            return [clean]

        return split_by_token_window(clean)


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
