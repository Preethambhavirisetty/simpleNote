from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any, Protocol


class LlmProvider(Protocol):
    def complete(self, messages: Sequence[dict[str, Any]], *, max_tokens: int = 1024) -> str:
        ...

    def stream(self, messages: Sequence[dict[str, Any]], *, max_tokens: int = 1024) -> Iterator[str]:
        ...
