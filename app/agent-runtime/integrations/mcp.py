"""Calling MCP tools, given a ToolCall the domain's mapping already resolved.

The rest of the runtime is synchronous while the MCP SDK is async, so each call
runs the SDK's client on its own short-lived event loop. That costs a connect
and an `initialize` handshake per tool call - a few milliseconds against a
local server, and negligible beside a retrieval call. `call_tool` is the seam:
a persistent session behind a background loop can replace the body without any
caller changing.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from config import MCP_SERVERS, MCP_TIMEOUT
from schemas.catalog import ToolCall


log = logging.getLogger(__name__)


class McpError(RuntimeError):
    """A tool could not be called, or reported failure."""


class ApprovalRequired(RuntimeError):
    """A destructive call reached the transport without being approved."""

    def __init__(self, call: ToolCall) -> None:
        super().__init__(
            f"{call.operation} requires approval before it can run"
        )
        self.call = call


def server_url(server: str) -> str:
    try:
        return MCP_SERVERS[server]
    except KeyError:
        known = ", ".join(sorted(MCP_SERVERS)) or "none configured"
        raise McpError(
            f"no URL configured for MCP server '{server}' (known: {known})"
        ) from None


def call_tool(call: ToolCall, *, approved: bool = False) -> Any:
    """Run one resolved tool call and return its payload.

    The approval gate lives here rather than in the steps: this is the single
    place every tool call passes through, so a step that forgets to check
    cannot reach the server anyway.
    """
    if call.requires_approval and not approved:
        raise ApprovalRequired(call)

    url = server_url(call.server)
    log.info(
        "calling mcp tool",
        extra={
            "tool": call.tool,
            "server": call.server,
            "operation": call.operation,
            "arguments": sorted(call.arguments),
        },
    )

    try:
        result = asyncio.run(_call(url, call))
    except McpError:
        raise
    except Exception as exc:  # transport, protocol, cancellation
        raise McpError(
            f"{call.tool} on {call.server} ({url}) failed: {_describe(exc)}"
        ) from exc

    return _payload(call, result)


def _describe(exc: BaseException) -> str:
    """Unwrap an ExceptionGroup to the causes that actually explain the failure.

    The SDK runs its transport in an anyio task group, so a refused connection
    surfaces as "unhandled errors in a TaskGroup (1 sub-exception)" unless the
    leaves are pulled out.
    """
    leaves: list[str] = []

    def walk(error: BaseException) -> None:
        if isinstance(error, BaseExceptionGroup):
            for nested in error.exceptions:
                walk(nested)
        else:
            leaves.append(f"{type(error).__name__}: {error}")

    walk(exc)
    return "; ".join(dict.fromkeys(leaves)) or f"{type(exc).__name__}: {exc}"


async def _call(url: str, call: ToolCall):
    timeout = timedelta(seconds=MCP_TIMEOUT)
    async with streamablehttp_client(url, timeout=MCP_TIMEOUT) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(
                call.tool, call.arguments, read_timeout_seconds=timeout
            )


def _payload(call: ToolCall, result: Any) -> Any:
    """Normalise an MCP result into the payload a step can work with.

    Notelite's tools return structured JSON objects and signal failure in the
    body with `ok: false` rather than by raising, so both the protocol-level
    error flag and the in-body flag have to be checked.
    """
    if getattr(result, "isError", False):
        raise McpError(f"{call.tool} reported an error: {_text(result)[:300]}")

    payload = getattr(result, "structuredContent", None)
    if payload is None:
        text = _text(result)
        if not text:
            return None
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return text

    # FastMCP wraps a non-dict return value; unwrap so callers see what the
    # tool actually returned.
    if isinstance(payload, dict) and set(payload) == {"result"}:
        payload = payload["result"]

    if isinstance(payload, dict) and payload.get("ok") is False:
        detail = payload.get("error") or payload.get("detail") or payload
        raise McpError(f"{call.tool} failed: {detail}")

    return payload


def _text(result: Any) -> str:
    return "".join(
        block.text
        for block in getattr(result, "content", []) or []
        if getattr(block, "type", None) == "text"
    )
