from __future__ import annotations

import math

import tiktoken


_ENCODING = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Count tokens with the service tokenizer and fall back to a character estimate."""
    if not text:
        return 0
    try:
        return len(_ENCODING.encode(text))
    except Exception:  # noqa: BLE001
        # Fallback for any unexpected tokenizer runtime issues.
        return max(1, math.ceil(len(text) / 4))
