from __future__ import annotations

from app.agent_workflow.config import McpServerConfig, ToolDiscoveryConfig
from app.agent_workflow.providers.mcp import _collect_index_targets


def test_collect_index_targets_from_server_configs():
    configs = [
        McpServerConfig(
            name="docs",
            url="http://example/mcp",
            tool_discovery=ToolDiscoveryConfig(
                mode="http_index",
                collections=["ct_user_connector"],
                owner_scope="550e8400-e29b-41d4-a716-446655440000",
                indexed=True,
            ),
        )
    ]
    collections, owner_scope, _search_url = _collect_index_targets(configs)
    assert collections == ["ct_user_connector"]
    assert owner_scope == "550e8400-e29b-41d4-a716-446655440000"


def test_collect_index_targets_skips_unindexed_servers():
    configs = [
        McpServerConfig(
            name="docs",
            url="http://example/mcp",
            tool_discovery=ToolDiscoveryConfig(indexed=False),
        )
    ]
    collections, owner_scope, _search_url = _collect_index_targets(configs)
    assert collections == []
    assert owner_scope == ""
