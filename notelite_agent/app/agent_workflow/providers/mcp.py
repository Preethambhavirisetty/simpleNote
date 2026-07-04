from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

import httpx

from app.shared.http import is_transient_http_error

from app.agent_workflow.config import McpConfig
from app.agent_workflow.providers.tools import ToolCandidate, ToolProvider

log = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2024-11-05"
SEMANTIC_SEARCH_TOOL = "semantic_tool_search"


def create_tool_provider(mcp: McpConfig) -> ToolProvider:
    url = (mcp.url or os.getenv("MCP_URL", "")).strip()
    if url:
        return RemoteMcpToolProvider(
            McpConfig(
                url=url,
                auth_token=mcp.auth_token or os.getenv("MCP_AUTH_TOKEN", ""),
                timeout_seconds=mcp.timeout_seconds,
                verify_ssl=mcp.verify_ssl,
            )
        )
    return InProcessMcpToolProvider()


class RemoteMcpToolProvider:
    def __init__(self, config: McpConfig):
        self.config = config
        self._request_id = 0
        self._id_lock = threading.Lock()
        self._init_lock = threading.Lock()
        self._initialized = False
        self._client = httpx.Client(timeout=self.config.timeout_seconds, verify=self.config.verify_ssl)

    def close(self) -> None:
        self._client.close()

    def search_tools(self, query: str, *, limit: int = 25) -> list[ToolCandidate]:
        result = self.call_tool(SEMANTIC_SEARCH_TOOL, {"query": query, "limit": limit})
        return _normalize_search_result(result)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        headers = self._headers()
        self._ensure_initialized(headers)
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_request_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }
        body = self._post_jsonrpc(payload, headers=headers)
        if "error" in body:
            raise RuntimeError(body["error"].get("message", "MCP tool call failed"))
        result = body.get("result") or {}
        content = result.get("content") or []
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
                    "params": None,
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


class InProcessMcpToolProvider:
    """Dev fallback when MCP_URL is unset."""

    def search_tools(self, query: str, *, limit: int = 25) -> list[ToolCandidate]:
        try:
            from app.helpers.mcp_tool_handler import semantic_search_tool
        except ImportError as exc:
            raise RuntimeError(
                "MCP_URL is not set and in-process mcp_tool_handler is unavailable"
            ) from exc
        return _normalize_search_result(semantic_search_tool(query, limit=limit))

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == SEMANTIC_SEARCH_TOOL:
            return self.search_tools(
                str(arguments.get("query", "")),
                limit=int(arguments.get("limit") or 25),
            )
        raise RuntimeError(
            f"In-process provider only supports {SEMANTIC_SEARCH_TOOL}; set MCP_URL for {name}"
        )


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
        name = str(payload.get("name") or "").strip()
        if not name:
            continue
        annotations = payload.get("annotations") if isinstance(payload.get("annotations"), dict) else {}
        candidates.append(
            ToolCandidate(
                name=name,
                title=str(annotations.get("title") or payload.get("title") or name),
                description=str(payload.get("description") or ""),
                score=float(item.get("score") or payload.get("score") or 0.0),
                input_schema=(
                    payload.get("inputSchema")
                    if isinstance(payload.get("inputSchema"), dict)
                    else payload.get("input_schema")
                    if isinstance(payload.get("input_schema"), dict)
                    else {}
                ),
            )
        )
    return candidates
