from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.shared.http import is_transient_http_error

from app.agent_workflow.config import McpConfig, McpServerConfig
from app.agent_workflow.providers.tools import ToolCandidate, ToolProvider

log = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2024-11-05"
SEMANTIC_SEARCH_TOOL = "semantic_tool_search"
_CATALOG_TTL_SECONDS = 300.0
_TOKEN_RE = re.compile(r"[a-z0-9_]+", re.IGNORECASE)


def create_tool_provider(mcp: McpConfig) -> ToolProvider:
    server_configs = _server_configs(mcp)
    if not server_configs:
        return EmptyToolProvider()
    providers = [RemoteMcpToolProvider(config) for config in server_configs]
    if len(providers) == 1:
        return providers[0]
    return MultiMcpToolProvider(providers)


def _server_configs(mcp: McpConfig) -> list[McpServerConfig]:
    configs = [server for server in (mcp.servers or []) if server.url]
    url = (mcp.url or os.getenv("MCP_URL", "")).strip()
    if url:
        configs.insert(
            0,
            McpServerConfig(
                name="default",
                url=url,
                auth_token=mcp.auth_token or os.getenv("MCP_AUTH_TOKEN", ""),
                timeout_seconds=mcp.timeout_seconds,
                verify_ssl=mcp.verify_ssl,
            ),
        )
    seen: set[str] = set()
    deduped: list[McpServerConfig] = []
    for idx, config in enumerate(configs):
        name = (config.name or f"server{idx + 1}").strip() or f"server{idx + 1}"
        base = name
        counter = 2
        while name in seen:
            name = f"{base}{counter}"
            counter += 1
        seen.add(name)
        deduped.append(
            McpServerConfig(
                name=name,
                url=config.url,
                auth_token=config.auth_token,
                timeout_seconds=config.timeout_seconds,
                verify_ssl=config.verify_ssl,
            )
        )
    return deduped


@dataclass
class _CatalogEntry:
    server_name: str
    raw_name: str
    exposed_name: str
    candidate: ToolCandidate


class MultiMcpToolProvider:
    def __init__(self, providers: list[RemoteMcpToolProvider]):
        self.providers = providers

    def close(self) -> None:
        for provider in self.providers:
            provider.close()

    def search_tools(self, query: str, *, limit: int = 25) -> list[ToolCandidate]:
        entries = self._catalog_entries()
        return _rank_catalog(entries, query, limit=limit)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        entries = self._catalog_entries()
        matches = [entry for entry in entries if name in {entry.exposed_name, entry.raw_name}]
        if len(matches) != 1:
            known = ", ".join(sorted(entry.exposed_name for entry in entries)[:20])
            raise RuntimeError(f"Unknown or ambiguous MCP tool {name!r}. Known tools: {known}")
        entry = matches[0]
        _validate_arguments(entry.candidate.name, arguments or {}, entry.candidate.input_schema)
        provider = next(provider for provider in self.providers if provider.server_name == entry.server_name)
        return provider.call_tool(entry.raw_name, arguments or {}, validate=False)

    def _catalog_entries(self) -> list[_CatalogEntry]:
        raw_entries: list[tuple[RemoteMcpToolProvider, ToolCandidate]] = []
        for provider in self.providers:
            for candidate in provider.list_tools():
                raw_entries.append((provider, candidate))

        name_counts: dict[str, int] = {}
        for _provider, candidate in raw_entries:
            name_counts[candidate.name] = name_counts.get(candidate.name, 0) + 1

        entries: list[_CatalogEntry] = []
        for provider, candidate in raw_entries:
            raw_name = candidate.name
            exposed_name = raw_name if name_counts.get(raw_name, 0) == 1 else f"{provider.server_name}:{raw_name}"
            if exposed_name != raw_name:
                candidate = ToolCandidate(
                    name=exposed_name,
                    title=candidate.title,
                    description=candidate.description,
                    score=candidate.score,
                    input_schema=candidate.input_schema,
                )
            entries.append(
                _CatalogEntry(
                    server_name=provider.server_name,
                    raw_name=raw_name,
                    exposed_name=exposed_name,
                    candidate=candidate,
                )
            )
        return entries


class RemoteMcpToolProvider:
    def __init__(self, config: McpServerConfig):
        self.config = config
        self.server_name = config.name or "default"
        self._request_id = 0
        self._id_lock = threading.Lock()
        self._init_lock = threading.Lock()
        self._catalog_lock = threading.Lock()
        self._initialized = False
        self._catalog_loaded_at = 0.0
        self._catalog: list[ToolCandidate] | None = None
        self._client = httpx.Client(timeout=self.config.timeout_seconds, verify=self.config.verify_ssl)

    def close(self) -> None:
        self._client.close()

    def search_tools(self, query: str, *, limit: int = 25) -> list[ToolCandidate]:
        try:
            result = self.call_tool(SEMANTIC_SEARCH_TOOL, {"query": query, "limit": limit})
            candidates = _normalize_search_result(result)
            if candidates:
                return candidates[:limit]
        except Exception as exc:  # noqa: BLE001
            log.debug("semantic MCP tool search unavailable; falling back to tools/list", extra={"server": self.server_name, "error": str(exc)})
        return _rank_catalog(
            [
                _CatalogEntry(
                    server_name=self.server_name,
                    raw_name=candidate.name,
                    exposed_name=candidate.name,
                    candidate=candidate,
                )
                for candidate in self.list_tools()
            ],
            query,
            limit=limit,
        )

    def list_tools(self) -> list[ToolCandidate]:
        now = time.time()
        with self._catalog_lock:
            if self._catalog is not None and now - self._catalog_loaded_at < _CATALOG_TTL_SECONDS:
                return list(self._catalog)

            tools: list[ToolCandidate] = []
            cursor: str | None = None
            for _page in range(20):
                params = {"cursor": cursor} if cursor else {}
                result = self._jsonrpc("tools/list", params)
                tools.extend(_normalize_list_tools_result(result))
                cursor = str(result.get("nextCursor") or result.get("next_cursor") or "").strip()
                if not cursor:
                    break

            self._catalog = tools
            self._catalog_loaded_at = now
            return list(tools)

    def call_tool(self, name: str, arguments: dict[str, Any], *, validate: bool = True) -> Any:
        if validate:
            schema = self._schema_for_tool(name)
            _validate_arguments(name, arguments or {}, schema)
        result = self._jsonrpc("tools/call", {"name": name, "arguments": arguments or {}})
        content = result.get("content") if isinstance(result, dict) else None
        if content and isinstance(content, list):
            text_parts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            ]
            joined = "".join(text_parts).strip()
            if joined:
                try:
                    return json.loads(joined)
                except json.JSONDecodeError:
                    return joined
        return result

    def _schema_for_tool(self, name: str) -> dict[str, Any]:
        catalog = self.list_tools()
        for candidate in catalog:
            if candidate.name == name:
                return candidate.input_schema
        if catalog:
            known = ", ".join(sorted(candidate.name for candidate in catalog)[:20])
            raise RuntimeError(f"Unknown MCP tool {name!r}. Known tools: {known}")
        return {}

    def _jsonrpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = self._headers()
        self._ensure_initialized(headers)
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_request_id(),
            "method": method,
            "params": params or {},
        }
        body = self._post_jsonrpc(payload, headers=headers)
        if "error" in body:
            raise RuntimeError(body["error"].get("message", f"MCP {method} failed"))
        return body.get("result") or {}

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.config.auth_token:
            headers["Authorization"] = f"Bearer {self.config.auth_token}"
        return headers

    def _next_request_id(self) -> int:
        with self._id_lock:
            self._request_id += 1
            return self._request_id

    def _ensure_initialized(self, headers: dict[str, str]) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            init_payload = {
                "jsonrpc": "2.0",
                "id": self._next_request_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "agent-workflow", "version": "1.0.0"},
                },
            }
            self._post_jsonrpc(init_payload, headers=headers)
            response = self._client.post(
                self.config.url,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {},
                },
            )
            response.raise_for_status()
            self._initialized = True

    def _post_jsonrpc(self, payload: dict[str, Any], *, headers: dict[str, str]) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                response = self._client.post(self.config.url, headers=headers, json=payload)
                response.raise_for_status()
                return _parse_jsonrpc_response(response.text)
            except httpx.HTTPError as exc:
                last_exc = exc
                if not is_transient_http_error(exc) or attempt == 2:
                    raise
                time.sleep(0.2 * (2 ** attempt))
        raise RuntimeError("MCP request failed") from last_exc


class EmptyToolProvider:
    """No MCP server configured; useful for fast-path-only apps and explicit test injection."""

    def search_tools(self, query: str, *, limit: int = 25) -> list[ToolCandidate]:
        return []

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        raise RuntimeError(f"No MCP servers are configured for tool call {name!r}")


def _parse_jsonrpc_response(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("{"):
        return json.loads(text)
    for line in text.splitlines():
        if line.startswith("data:"):
            data = line[5:].strip()
            if data and data != "[DONE]":
                return json.loads(data)
    raise RuntimeError("Could not parse MCP JSON-RPC response")


def _normalize_list_tools_result(result: Any) -> list[ToolCandidate]:
    if not isinstance(result, dict):
        return []
    return [_candidate_from_payload(item, 0.0) for item in (result.get("tools") or []) if isinstance(item, dict)]


def _normalize_search_result(result: Any) -> list[ToolCandidate]:
    if isinstance(result, list):
        items = result
    elif isinstance(result, dict):
        if not result.get("ok", True) and result.get("error"):
            raise RuntimeError(str(result["error"]))
        items = result.get("tools") or result.get("results") or []
    else:
        return []

    candidates: list[ToolCandidate] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else item
        candidate = _candidate_from_payload(payload, float(item.get("score") or payload.get("score") or 0.0))
        if candidate.name:
            candidates.append(candidate)
    return candidates


def _candidate_from_payload(payload: dict[str, Any], score: float) -> ToolCandidate:
    name = str(payload.get("name") or "").strip()
    annotations = payload.get("annotations") if isinstance(payload.get("annotations"), dict) else {}
    schema = payload.get("inputSchema") if isinstance(payload.get("inputSchema"), dict) else payload.get("input_schema")
    return ToolCandidate(
        name=name,
        title=str(annotations.get("title") or payload.get("title") or name),
        description=str(payload.get("description") or ""),
        score=score,
        input_schema=schema if isinstance(schema, dict) else {},
    )


def _rank_catalog(entries: list[_CatalogEntry], query: str, *, limit: int) -> list[ToolCandidate]:
    query_tokens = _tokens(query)
    ranked: list[tuple[float, ToolCandidate]] = []
    for entry in entries:
        candidate = entry.candidate
        haystack = " ".join([candidate.name, candidate.title, candidate.description])
        hay_tokens = _tokens(haystack)
        overlap = len(query_tokens & hay_tokens)
        coverage = overlap / max(1, len(query_tokens))
        density = overlap / math.sqrt(max(1, len(hay_tokens)))
        exact_bonus = 0.25 if query.lower() and query.lower() in haystack.lower() else 0.0
        score = float(candidate.score or 0.0) + coverage + density + exact_bonus
        ranked.append((score, ToolCandidate(
            name=candidate.name,
            title=candidate.title,
            description=candidate.description,
            score=score,
            input_schema=candidate.input_schema,
        )))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [candidate for _score, candidate in ranked[:limit]]


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(text) if len(token) > 2}


def _validate_arguments(tool_name: str, arguments: dict[str, Any], schema: dict[str, Any]) -> None:
    errors = _argument_errors(arguments, schema)
    if errors:
        raise ValueError(f"Invalid arguments for {tool_name}: {'; '.join(errors)}")


def _argument_errors(arguments: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    if not schema:
        return []
    errors: list[str] = []
    schema_type = schema.get("type")
    if schema_type and not _matches_json_type(arguments, schema_type):
        return [f"arguments must match JSON schema type {schema_type!r}"]
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    for field in required:
        if field not in arguments or arguments.get(field) is None:
            errors.append(f"missing required argument: {field}")
    if schema.get("additionalProperties") is False and properties:
        for field in sorted(set(arguments) - set(properties)):
            errors.append(f"unexpected argument: {field}")
    for field, value in arguments.items():
        field_schema = properties.get(field)
        if not isinstance(field_schema, dict):
            continue
        expected = field_schema.get("type")
        if expected and not _matches_json_type(value, expected):
            errors.append(f"argument {field} must match JSON schema type {expected!r}")
    return errors


def _matches_json_type(value: Any, expected: Any) -> bool:
    if isinstance(expected, list):
        return any(_matches_json_type(value, item) for item in expected)
    if not expected:
        return True
    if expected == "null":
        return value is None
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return True
