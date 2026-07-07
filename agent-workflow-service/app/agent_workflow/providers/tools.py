from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class ToolCandidate:
    """Search result describing one available tool."""
    name: str
    title: str
    description: str
    score: float
    input_schema: dict[str, Any]


class ToolProvider(Protocol):
    """Protocol required by workflow tool providers."""
    def search_tools(
        self,
        query: str,
        *,
        limit: int = 25,
        allowlist: list[str] | None = None,
    ) -> list[ToolCandidate]:
        """Search tools and return matching candidates."""
        ...

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call tool and return the provider result."""
        ...
