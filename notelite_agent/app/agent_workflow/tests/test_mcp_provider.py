from __future__ import annotations

import pytest

from app.agent_workflow.config import McpConfig, McpServerConfig
from app.agent_workflow.providers.mcp import EmptyToolProvider, MultiMcpToolProvider, create_tool_provider
from app.agent_workflow.providers.tools import ToolCandidate


class FakeProvider:
    def __init__(self, server_name: str, tools: list[ToolCandidate]):
        self.server_name = server_name
        self._tools = tools
        self.calls: list[tuple[str, dict]] = []

    def list_tools(self) -> list[ToolCandidate]:
        return list(self._tools)

    def call_tool(self, name: str, arguments: dict, *, validate: bool = True):
        self.calls.append((name, arguments))
        return {"ok": True, "server": self.server_name, "tool": name, "arguments": arguments}

    def close(self) -> None:
        pass


def tool(name: str, description: str, schema: dict | None = None) -> ToolCandidate:
    return ToolCandidate(
        name=name,
        title=name.replace("_", " ").title(),
        description=description,
        score=0.0,
        input_schema=schema or {},
    )


def test_create_tool_provider_accepts_multiple_mcp_servers():
    provider = create_tool_provider(
        McpConfig(
            servers=[
                McpServerConfig(name="notes", url="http://notes.example/mcp"),
                McpServerConfig(name="jira", url="http://jira.example/mcp"),
            ]
        )
    )

    assert isinstance(provider, MultiMcpToolProvider)


def test_create_tool_provider_without_servers_returns_empty_provider():
    provider = create_tool_provider(McpConfig())

    assert isinstance(provider, EmptyToolProvider)
    assert provider.search_tools("anything") == []


def test_multi_provider_aggregates_and_qualifies_duplicate_tool_names():
    notes = FakeProvider("notes", [tool("search", "Search notes and folders")])
    docs = FakeProvider("docs", [tool("search", "Search documents and pages")])
    provider = MultiMcpToolProvider([notes, docs])

    candidates = provider.search_tools("documents", limit=5)

    names = {candidate.name for candidate in candidates}
    assert "notes:search" in names
    assert "docs:search" in names

    result = provider.call_tool("docs:search", {"query": "SLA"})

    assert result["server"] == "docs"
    assert docs.calls == [("search", {"query": "SLA"})]
    assert notes.calls == []


def test_multi_provider_validates_against_input_schema_before_dispatch():
    provider = MultiMcpToolProvider(
        [
            FakeProvider(
                "notes",
                [
                    tool(
                        "search_notes",
                        "Search notes",
                        {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                            "required": ["query"],
                            "additionalProperties": False,
                        },
                    )
                ],
            )
        ]
    )

    with pytest.raises(ValueError, match="missing required argument: query"):
        provider.call_tool("search_notes", {})
