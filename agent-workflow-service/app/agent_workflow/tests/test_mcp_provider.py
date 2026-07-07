from __future__ import annotations

import pytest

from app.agent_workflow.config import McpConfig, McpServerConfig
from app.agent_workflow.providers.mcp import EmptyToolProvider, MultiMcpToolProvider, RemoteMcpToolProvider, create_tool_provider
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


def test_create_tool_provider_uses_runtime_servers_instead_of_default_env(monkeypatch):
    monkeypatch.setenv("MCP_URL", "http://default.example/mcp")
    monkeypatch.setenv("MCP_AUTH_TOKEN", "default-token")

    provider = create_tool_provider(
        McpConfig(
            url="http://default.example/mcp",
            auth_token="default-token",
            servers=[McpServerConfig(name="splunk", url="http://splunk.example/mcp", auth_token="splunk-token")],
        )
    )

    assert isinstance(provider, RemoteMcpToolProvider)
    assert provider.config.url == "http://splunk.example/mcp"
    assert provider.config.auth_token == "splunk-token"


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


def test_http_tool_index_provider_sends_allowlist(monkeypatch):
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"ok": True, "tools": []}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("app.agent_workflow.providers.tool_index.httpx.Client", FakeClient)

    from app.agent_workflow.providers.tool_index import HttpToolIndexProvider

    provider = HttpToolIndexProvider(search_url="http://example/internal/connector-tools/search")
    provider.search_tools(
        owner_scope="550e8400-e29b-41d4-a716-446655440000",
        collections=["ct_550e8400e29b41d4a716446655440000_tools"],
        allowlist=["list_dashboards"],
        query="dashboards",
        limit=10,
    )

    payload = captured["json"]
    assert payload["allowlist"] == ["list_dashboards"]
