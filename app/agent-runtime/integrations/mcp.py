"""Calling MCP tools through persistent, pooled client sessions."""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import threading
from builtins import BaseExceptionGroup
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import timedelta
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from config import MCP_SERVERS, MCP_TIMEOUT
from integrations import observability as obs
from schemas.catalog import ToolCall

log = logging.getLogger(__name__)


class _ServerConnection:
    """A session whose transport is entered, used, and exited by one task."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.queue: asyncio.Queue[tuple[ToolCall, asyncio.Future] | None] = (
            asyncio.Queue()
        )
        self.ready = asyncio.get_running_loop().create_future()
        self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            async with (
                streamablehttp_client(self.url, timeout=MCP_TIMEOUT) as (
                    read,
                    write,
                    _,
                ),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                self.ready.set_result(None)
                while True:
                    item = await self.queue.get()
                    if item is None:
                        return
                    call, result = item
                    try:
                        value = await session.call_tool(
                            call.tool,
                            call.arguments,
                            read_timeout_seconds=timedelta(seconds=MCP_TIMEOUT),
                        )
                    except Exception as exc:  # noqa: BLE001 - forwarded to sync caller
                        if not result.done():
                            result.set_exception(exc)
                    else:
                        if not result.done():
                            result.set_result(value)
        except Exception as exc:  # noqa: BLE001 - fail queued callers on transport loss
            if not self.ready.done():
                self.ready.set_exception(exc)
            while not self.queue.empty():
                item = self.queue.get_nowait()
                if item is not None and not item[1].done():
                    item[1].set_exception(exc)

    async def call(self, call: ToolCall):
        await self.ready
        result = asyncio.get_running_loop().create_future()
        await self.queue.put((call, result))
        return await result

    async def close(self) -> None:
        if not self.task.done():
            await self.queue.put(None)
        await asyncio.gather(self.task, return_exceptions=True)


class _McpPool:
    """Own one background event loop and one initialized session per server."""

    def __init__(self) -> None:
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="mcp-client-pool", daemon=True
        )
        self._thread.start()
        self._ready.wait()

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._connections: dict[str, _ServerConnection] = {}
        self._ready.set()
        self._loop.run_forever()
        self._loop.close()

    async def _call(self, url: str, call: ToolCall):
        connection = self._connections.get(url)
        if connection is None or connection.task.done():
            connection = _ServerConnection(url)
            self._connections[url] = connection
        return await connection.call(call)

    def call(self, url: str, call: ToolCall):
        future = asyncio.run_coroutine_threadsafe(self._call(url, call), self._loop)
        try:
            return future.result(timeout=MCP_TIMEOUT + 5)
        except FutureTimeoutError:
            future.cancel()
            raise

    def close(self) -> None:
        if self._thread.is_alive():
            shutdown = asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)
            try:
                shutdown.result(timeout=5)
            except FutureTimeoutError:
                shutdown.cancel()
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)

    async def _shutdown(self) -> None:
        await asyncio.gather(
            *(connection.close() for connection in self._connections.values()),
            return_exceptions=True,
        )


_pool: _McpPool | None = None
_pool_lock = threading.Lock()


def _client_pool() -> _McpPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = _McpPool()
                atexit.register(_pool.close)
    return _pool


class McpError(RuntimeError):
    """A tool could not be called, or reported failure."""


class ApprovalRequired(RuntimeError):
    """A destructive call reached the transport without being approved."""

    def __init__(self, call: ToolCall) -> None:
        super().__init__(f"{call.operation} requires approval before it can run")
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

    obs.debug(
        "calling %s on %s",
        call.tool,
        call.server,
        phase="tool",
        data={
            "url": url,
            "arguments": obs.preview(call.arguments),
            "destructive": call.destructive,
        },
    )

    try:
        with obs.timed("tool", f"mcp {call.tool}") as timer:
            result = _client_pool().call(url, call)
            timer.track(
                tool=call.tool, mcp_server=call.server, operation=call.operation
            )
    except McpError:
        raise
    except Exception as exc:  # transport, protocol, cancellation
        detail = _describe(exc)
        obs.error(
            "%s failed: %s",
            call.tool,
            detail,
            phase="tool",
            track={"tool_error": call.tool},
        )
        raise McpError(
            f"{call.tool} on {call.server} ({url}) failed: {detail}"
        ) from exc

    payload = _payload(call, result)
    obs.debug(
        "%s returned",
        call.tool,
        phase="tool",
        data={"payload": obs.preview(payload)},
        track={
            "tool_result_keys": sorted(payload)[:10]
            if isinstance(payload, dict)
            else None
        },
    )
    return payload


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
