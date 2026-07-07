from __future__ import annotations

from app.api.runtime_bundle_adapter import (
    build_runtime_overrides,
    runtime_agent_from_bundle,
)


def _sample_runtime_bundle() -> dict:
    return {
        "agent": {"id": "agent-1", "db_id": 7, "name": "Splunk Agent", "status": "deployed"},
        "active_version": {
            "id": 12,
            "instructions": "Use Splunk tools only.",
            "model": "the-inference/reasoner",
            "config_hash": "abc123",
            "connectors": [
                {
                    "name": "splunk",
                    "config": {
                        "url": "http://127.0.0.1:8970/mcp",
                        "headers": {"Authorization": "Bearer test-token"},
                        "timeout": 30000,
                        "verify_ssl": True,
                    },
                    "active_tools": ["list_dashboards"],
                }
            ],
            "tools": {"active_tools": ["list_dashboards"]},
            "tool_manifest": [{"name": "list_dashboards"}],
            "config": {"runtime": {}},
        },
        "adapter_payload": {
            "runtime_agent": "customized",
            "agent_record": {
                "config": {
                    "instructions": "Use Splunk tools only.",
                    "model": "the-inference/reasoner",
                }
            },
        },
    }


def test_runtime_agent_from_bundle_recognizes_customized():
    assert runtime_agent_from_bundle(_sample_runtime_bundle()) == "customized"
    assert runtime_agent_from_bundle({"adapter_payload": {"runtime_agent": "generic"}}) == "generic"


def test_build_runtime_overrides_maps_instructions_model_and_mcp_servers():
    overrides = build_runtime_overrides(_sample_runtime_bundle())

    assert overrides["name"] == "Splunk Agent"
    assert overrides["prompts_inline"]["executor"] == "Use Splunk tools only."
    assert overrides["policy"]["instructions"] == "Use Splunk tools only."
    assert overrides["llm"]["model"] == "the-inference/reasoner"
    assert len(overrides["mcp"]["servers"]) == 1
    server = overrides["mcp"]["servers"][0]
    assert server["name"] == "splunk"
    assert server["url"] == "http://127.0.0.1:8970/mcp"
    assert server["auth_token"] == "test-token"
    assert server["timeout_seconds"] == 30.0
    assert overrides["policy"]["tools"]["allowlist"] == ["list_dashboards"]


def test_build_runtime_overrides_uses_connector_active_tools_when_top_level_empty():
    bundle = _sample_runtime_bundle()
    bundle["active_version"]["tools"]["active_tools"] = []
    bundle["active_version"]["connectors"][0]["active_tools"] = [
        "list_dashboards",
        "search_panels",
        "get_dashboard",
        "get_panel_data",
    ]
    bundle["active_version"]["tool_manifest"] = [
        {"name": "qdrant_query_collection_exact"},
        {"name": "list_dashboards"},
    ]

    overrides = build_runtime_overrides(bundle)

    assert overrides["policy"]["tools"]["allowlist"] == [
        "list_dashboards",
        "search_panels",
        "get_dashboard",
        "get_panel_data",
    ]


def test_build_runtime_overrides_merges_top_level_runtime_overrides():
    bundle = _sample_runtime_bundle()
    bundle["runtime_overrides"] = {
        "policy": {"enable_planner": False},
        "prompts_inline": {"reviewer": "Be strict."},
    }
    overrides = build_runtime_overrides(bundle)
    assert overrides["policy"]["enable_planner"] is False
    assert overrides["prompts_inline"]["reviewer"] == "Be strict."
