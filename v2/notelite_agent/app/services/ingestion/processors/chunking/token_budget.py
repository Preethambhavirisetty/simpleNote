from __future__ import annotations

import tiktoken

from app.core.config import CHUNK_OVERLAP, MAX_CHUNK_SIZE
from app.shared.utils import count_tokens


_ENCODER = tiktoken.get_encoding("cl100k_base")


def token_count(text: str) -> int:
    return count_tokens(text)


def within_chunk_budget(text: str) -> bool:
    return token_count(text) <= MAX_CHUNK_SIZE


def within_overlap_budget(text: str) -> bool:
    return token_count(text) <= CHUNK_OVERLAP


def split_by_token_window(text: str) -> list[str]:
    clean = text.strip()
    if not clean:
        return []

    tokens = _ENCODER.encode(clean)
    if len(tokens) <= MAX_CHUNK_SIZE:
        return [clean]

    overlap = max(0, min(CHUNK_OVERLAP, max(0, MAX_CHUNK_SIZE - 1)))
    step = max(1, MAX_CHUNK_SIZE - overlap)

    parts = []
    start = 0
    while start < len(tokens):
        window = tokens[start : start + MAX_CHUNK_SIZE]
        piece = _ENCODER.decode(window).strip()
        if piece:
            parts.append(piece)

        if start + MAX_CHUNK_SIZE >= len(tokens):
            break
        start += step

    return parts
