import os
from functools import lru_cache

import tiktoken

enc = tiktoken.get_encoding("cl100k_base")

# Chunking asks for the token count of the same strings repeatedly - a document
# is measured whole, then per structural chunk, then per sentence while windows
# are packed, then again while keyword batches are budgeted. Measured on a 19KB
# note: 490 encode() calls covering 6.3x the document's characters.
#
# Bounded so a long ingestion cannot grow the cache without limit; the entries
# that matter (sentences and chunks, re-measured within one document) are small
# and short-lived.
_TOKEN_CACHE_MAX_ENTRIES = 4096
# Only cache what gets re-measured. Whole documents are counted once or twice
# and would evict thousands of useful sentence entries.
_TOKEN_CACHE_MAX_CHARS = 20_000


@lru_cache(maxsize=_TOKEN_CACHE_MAX_ENTRIES)
def _cached_token_count(text: str) -> int:
    return len(enc.encode(text))


def count_tokens(text):
    if not text:
        return 0
    if len(text) > _TOKEN_CACHE_MAX_CHARS:
        return len(enc.encode(text))
    return _cached_token_count(text)


def build_llm_messages(system_prompt: str, text:str):
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": text}
    ]

def require_env(key: str, default:str=None) -> str:
    value = os.getenv(key, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value
