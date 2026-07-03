import re

from app.core.config import MAX_CHUNK_SIZE
from app.services.ingestion.processors.chunking.token_budget import (
    split_by_token_window,
    token_count,
    within_chunk_budget,
)
from app.services.ingestion.processors.chunking.validators import (
    is_fenced_code_block,
    is_table_like,
    is_table_rowish_chunk,
    split_preserving_fenced_code_blocks,
)


_sentencizer = None


class WindowChunker:
    """Final size splitter using sentence-aware and table-aware boundaries."""

    def split(self, text: str) -> list[str]:
        clean = text.strip()
        if not clean:
            return []
        if within_chunk_budget(clean):
            return [clean]

        parts: list[str] = []
        for segment in split_preserving_fenced_code_blocks(clean):
            if is_fenced_code_block(segment):
                parts.append(segment.strip())
                continue

            if within_chunk_budget(segment):
                parts.append(segment.strip())
                continue

            if is_table_like(segment):
                parts.extend(self._split_table_rows(segment))
                continue

            sentences = self._split_sentences(segment)
            if len(sentences) <= 1:
                parts.extend(self._hard_split(segment))
                continue

            parts.extend(self._merge_sentence_windows(sentences))

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
                current = []
                current_len = 0

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

    def _split_table_rows(self, text: str) -> list[str]:
        parts: list[str] = []
        current: list[str] = []
        header_context = self._table_header_context(text)

        for line in [line.rstrip() for line in text.splitlines() if line.strip()]:
            candidate_lines = [*current, line]
            candidate = "\n".join(candidate_lines).strip()
            if current and not within_chunk_budget(candidate):
                parts.append("\n".join(current).strip())
                current = [*header_context]
                if line not in current:
                    current.append(line)
                continue

            current = candidate_lines

        if current:
            parts.append("\n".join(current).strip())

        output: list[str] = []
        for part in parts:
            if within_chunk_budget(part) or is_table_rowish_chunk(part):
                output.append(part)
            else:
                output.extend(self._merge_sentence_windows(self._split_sentences(part)))
        return [part for part in output if part]

    @staticmethod
    def _table_header_context(text: str) -> list[str]:
        lines = [line.rstrip() for line in text.splitlines() if line.strip()]
        for index, line in enumerate(lines[:-1]):
            next_line = lines[index + 1].strip()
            if line.count("|") >= 2 and re.match(r"^\|?[-: ]+\|[-|: ]+\|?$", next_line):
                return [line, lines[index + 1]]
        return []

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

        return split_by_token_window(clean, overlap_tokens=0)


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
