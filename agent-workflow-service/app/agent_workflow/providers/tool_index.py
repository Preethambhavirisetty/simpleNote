from __future__ import annotations

import logging
import os
from typing import Protocol

import httpx

from app.agent_workflow.providers.tools import ToolCandidate

log = logging.getLogger(__name__)

DEFAULT_SEARCH_URL = (os.getenv("TOOL_INDEX_SEARCH_URL") or "").strip()
DEFAULT_API_KEY = (os.getenv("TOOL_INDEX_API_KEY") or os.getenv("MCP_INTERNAL_KEY") or "").strip()


class ToolIndexProvider(Protocol):
    """Protocol for semantic tool-index backends."""
    def search_tools(
        self,
        *,
        owner_scope: str,
        collections: list[str],
        allowlist: list[str] | None = None,
        query: str,
        limit: int = 25,
    ) -> list[ToolCandidate]:
        """Search the semantic tool index and return matching candidates."""
        ...


class NullToolIndexProvider:
    """Disabled semantic tool-index provider."""
    def search_tools(
        self,
        *,
        owner_scope: str,
        collections: list[str],
        allowlist: list[str] | None = None,
        query: str,
        limit: int = 25,
    ) -> list[ToolCandidate]:
        """Search tools and return matching candidates."""
        return []


class HttpToolIndexProvider:
    """HTTP client for the semantic tool-index service."""
    def __init__(self, search_url: str, api_key: str = "") -> None:
        """Initialize this object with its runtime dependencies."""
        self.search_url = search_url.rstrip("/")
        self.api_key = api_key.strip()

    @property
    def available(self) -> bool:
        """Return whether this provider has enough configuration to run."""
        return bool(self.search_url)

    @classmethod
    def from_env(cls) -> HttpToolIndexProvider:
        """Create a provider from TOOL_INDEX_* environment settings."""
        return cls(search_url=DEFAULT_SEARCH_URL, api_key=DEFAULT_API_KEY)

    def search_tools(
        self,
        *,
        owner_scope: str,
        collections: list[str],
        allowlist: list[str] | None = None,
        query: str,
        limit: int = 25,
    ) -> list[ToolCandidate]:
        """Search tools and return matching candidates."""
        if not self.available or not collections:
            return []
        cleaned_allowlist = [str(item).strip() for item in (allowlist or []) if str(item).strip()]
        payload = {
            "version": 1,
            "owner_scope": owner_scope,
            "owner_user_id": owner_scope,
            "collections": collections,
            "allowlist": cleaned_allowlist,
            "query": query,
            "limit": max(1, min(limit, 50)),
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-Internal-Key"] = self.api_key
        try:
            with httpx.Client(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
                response = client.post(self.search_url, headers=headers, json=payload)
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPError as exc:
            log.debug("tool index search failed: %s", exc)
            return []
        if not isinstance(body, dict) or not body.get("ok", True):
            return []
        tools = body.get("tools") if isinstance(body.get("tools"), list) else []
        candidates: list[ToolCandidate] = []
        for item in tools:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            annotations = item.get("annotations") if isinstance(item.get("annotations"), dict) else {}
            schema = item.get("inputSchema") if isinstance(item.get("inputSchema"), dict) else item.get("input_schema")
            candidates.append(
                ToolCandidate(
                    name=name,
                    title=str(annotations.get("title") or item.get("title") or name),
                    description=str(item.get("description") or ""),
                    score=float(item.get("score") or 0.0),
                    input_schema=schema if isinstance(schema, dict) else {},
                )
            )
        return candidates
