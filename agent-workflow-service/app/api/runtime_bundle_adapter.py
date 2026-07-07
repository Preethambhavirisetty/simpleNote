from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent_workflow.engine import AgentEngine


_DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[1] / "agent_workflow" / "agents" / "default.yaml"
)

_RUNTIME_AGENT_CUSTOMIZED = "customized"


def _extract_bearer_token(headers: dict[str, Any]) -> str:
    auth = str(headers.get("Authorization") or headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _connector_auth_token(config: dict[str, Any]) -> str:
    token = str(config.get("auth_token") or "").strip()
    if token and token != "********":
        return token
    headers = config.get("headers") if isinstance(config.get("headers"), dict) else {}
    return _extract_bearer_token(headers)


def _connector_to_mcp_server(connector: dict[str, Any]) -> dict[str, Any]:
    config = connector.get("config") if isinstance(connector.get("config"), dict) else {}
    timeout_raw = config.get("timeout", 30000)
    try:
        timeout_seconds = max(1.0, float(timeout_raw) / 1000.0)
    except (TypeError, ValueError):
        timeout_seconds = 120.0
    server: dict[str, Any] = {
        "name": str(connector.get("name") or "connector").strip() or "connector",
        "url": str(config.get("url") or "").strip(),
        "auth_token": _connector_auth_token(config),
        "timeout_seconds": timeout_seconds,
        "verify_ssl": bool(config.get("verify_ssl", True)),
    }
    proxy_url = str(config.get("proxy_url") or "").strip()
    if proxy_url:
        server["proxy_url"] = proxy_url
    tool_index = connector.get("tool_index") if isinstance(connector.get("tool_index"), dict) else {}
    if tool_index.get("indexed") and tool_index.get("collection"):
        server["tool_discovery"] = {
            "mode": "http_index",
            "collections": [str(tool_index["collection"])],
            "owner_scope": str(connector.get("owner_user_id") or ""),
            "indexed": True,
        }
    return server


def _normalize_tool_names(names: list[str] | None) -> list[str]:
    return list(dict.fromkeys(str(name).strip() for name in (names or []) if str(name).strip()))


def _connector_active_tools(connectors: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for connector in connectors or []:
        if not isinstance(connector, dict):
            continue
        for tool in connector.get("active_tools") or []:
            name = str(tool).strip()
            if name:
                names.append(name)
    return _normalize_tool_names(names)


def _collect_allowlist(version: dict[str, Any]) -> list[str]:
    """Resolve tool allowlist from version snapshot.

    Prefer explicit top-level active_tools. When empty, use the union of
    connectors[].active_tools. Do not fall back to the full tool_manifest.
    """
    tools = version.get("tools") if isinstance(version.get("tools"), dict) else {}
    version_config = version.get("config") if isinstance(version.get("config"), dict) else {}
    connectors = version.get("connectors") if isinstance(version.get("connectors"), list) else []

    top_level = tools.get("active_tools")
    if not isinstance(top_level, list):
        top_level = version_config.get("active_tools")

    allowlist = _normalize_tool_names(top_level if isinstance(top_level, list) else None)
    if allowlist:
        return allowlist
    return _connector_active_tools(connectors)


def build_runtime_overrides(runtime_bundle: dict[str, Any]) -> dict[str, Any]:
    """Map backend runtime bundle into agent_workflow runtime_overrides."""
    agent_info = runtime_bundle.get("agent") if isinstance(runtime_bundle.get("agent"), dict) else {}
    version = runtime_bundle.get("active_version") if isinstance(runtime_bundle.get("active_version"), dict) else {}
    adapter_payload = runtime_bundle.get("adapter_payload") if isinstance(runtime_bundle.get("adapter_payload"), dict) else {}
    agent_record = adapter_payload.get("agent_record") if isinstance(adapter_payload.get("agent_record"), dict) else {}
    record_config = agent_record.get("config") if isinstance(agent_record.get("config"), dict) else {}

    instructions = str(
        version.get("instructions")
        or record_config.get("instructions")
        or ""
    ).strip()
    model = str(version.get("model") or record_config.get("model") or "").strip()
    agent_name = str(agent_info.get("name") or version.get("name") or "agent").strip() or "agent"

    connectors = version.get("connectors") or record_config.get("connectors") or []
    mcp_servers = [
        _connector_to_mcp_server(connector)
        for connector in connectors
        if isinstance(connector, dict)
    ]

    overrides: dict[str, Any] = {
        "name": agent_name,
        "prompts_inline": {
            "executor": instructions,
        },
        "policy": {
            "instructions": instructions,
            "model": model or None,
        },
        "mcp": {
            "servers": mcp_servers,
        },
    }

    allowlist = _collect_allowlist(version)
    if allowlist:
        overrides.setdefault("policy", {})["tools"] = {"allowlist": allowlist}

    runtime_config = version.get("config", {}).get("runtime") if isinstance(version.get("config"), dict) else {}
    if isinstance(runtime_config, dict) and runtime_config:
        for key, value in runtime_config.items():
            if key in {"policy", "prompts_inline", "llm", "mcp"} and isinstance(value, dict):
                overrides[key] = deepcopy(value)
            elif key == "name" and isinstance(value, str):
                overrides["name"] = value.strip()

    if model:
        overrides["llm"] = {"model": model}

    top_level_overrides = runtime_bundle.get("runtime_overrides")
    if isinstance(top_level_overrides, dict) and top_level_overrides:
        for key, value in top_level_overrides.items():
            if isinstance(value, dict) and isinstance(overrides.get(key), dict):
                merged = deepcopy(overrides[key])
                merged.update(deepcopy(value))
                overrides[key] = merged
            else:
                overrides[key] = deepcopy(value)

    return overrides


def build_engine_from_runtime_bundle(runtime_bundle: dict[str, Any]) -> AgentEngine:
    from app.agent_workflow.engine import AgentEngine

    overrides = build_runtime_overrides(runtime_bundle)
    return AgentEngine.from_runtime_config(_DEFAULT_CONFIG_PATH, overrides)


def runtime_agent_from_bundle(runtime_bundle: dict[str, Any] | None) -> str:
    if not runtime_bundle:
        return "generic"
    adapter_payload = runtime_bundle.get("adapter_payload")
    if not isinstance(adapter_payload, dict):
        return "generic"
    runtime_agent = str(adapter_payload.get("runtime_agent") or "generic").strip().lower()
    if runtime_agent == _RUNTIME_AGENT_CUSTOMIZED:
        return _RUNTIME_AGENT_CUSTOMIZED
    return "generic"
