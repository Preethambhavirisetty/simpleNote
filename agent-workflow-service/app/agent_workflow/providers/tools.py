from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class ToolCandidate:
    name: str
    title: str
    description: str
    score: float
    input_schema: dict[str, Any]


class ToolProvider(Protocol):
    def search_tools(self, query: str, *, limit: int = 25) -> list[ToolCandidate]:
        ...

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        ...
