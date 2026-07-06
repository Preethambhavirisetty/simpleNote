from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any, Protocol


class LlmProvider(Protocol):
    """Protocol required by workflow LLM providers."""
    def complete(self, messages: Sequence[dict[str, Any]], *, max_tokens: int = 1024) -> str:
        """Run one non-streaming LLM completion request."""
        ...

    def stream(self, messages: Sequence[dict[str, Any]], *, max_tokens: int = 1024) -> Iterator[str]:
        """Run one streaming LLM completion request."""
        ...
