from __future__ import annotations

import importlib
import os
import math
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = PROJECT_ROOT / "app"
MCP_APP_ROOT = Path(__file__).resolve().parent


def _load_fastmcp() -> Any:
    """Load the installed MCP SDK despite this app directory also being named mcp."""
    original_path = list(sys.path)
    local_package = sys.modules.pop("mcp", None)
    blocked_paths = {APP_ROOT, MCP_APP_ROOT}
    try:
        sys.path = [
            entry
            for entry in sys.path
            if Path(entry or ".").resolve() not in blocked_paths
        ]
        return importlib.import_module("mcp.server.fastmcp").FastMCP
    finally:
        sys.path = original_path
        if local_package is not None:
            sys.modules["mcp"] = local_package


FastMCP = _load_fastmcp()

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


mcp = FastMCP("Notelite Tools")


_TOOL_CATALOG: list[dict[str, Any]] = [
    {
        "name": "search_notes",
        "title": "Gather Evidence From Notes",
        "description": (
            "Use the full Notelite retrieval pipeline to gather answer-ready evidence "
            "from a user's notes. This performs query contextualization, temporal "
            "filtering, HyDE expansion, dense and sparse multi-collection search, "
            "reciprocal-rank fusion, reranking, neighbor expansion, and summaries."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The user's information need."},
                "user_id": {"type": "string", "description": "Tenant/user scope for notes."},
                "k": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 12,
                    "description": "Maximum reranked seed chunks before context expansion.",
                },
                "role": {
                    "type": "string",
                    "enum": ["user", "admin"],
                    "default": "user",
                    "description": "Caller role. Retrieval remains scoped to user_id.",
                },
                "history": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {"type": "string"},
                            "content": {"type": "string"},
                        },
                    },
                    "description": "Recent chat messages used to resolve short follow-ups.",
                },
                "include_context": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include bounded retrieval context text previews.",
                },
                "include_diagnostics": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include retrieval stage diagnostics for debugging.",
                },
            },
            "required": ["query", "user_id"],
        },
        "annotations": {
            "title": "Gather Evidence From Notes",
            "readOnlyHint": True,
            "openWorldHint": False,
        },
        "keywords": [
            "rag",
            "retrieve",
            "evidence",
            "notes",
            "answer",
            "context",
            "summaries",
            "chunks",
            "question",
            "search",
        ],
    },
    {
        "name": "locate_notes",
        "title": "Locate Relevant Notes",
        "description": (
            "Find the notes most likely to contain requested information and return "
            "note-level references, folder placement, matching chunk ids, snippets, "
            "keywords, entities, and relevance signals."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to find in notes."},
                "user_id": {"type": "string", "description": "Tenant/user scope for notes."},
                "k": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10,
                    "description": "Maximum reranked seed chunks before grouping by note.",
                },
                "role": {"type": "string", "enum": ["user", "admin"], "default": "user"},
                "history": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Recent chat messages used to resolve short follow-ups.",
                },
            },
            "required": ["query", "user_id"],
        },
        "annotations": {
            "title": "Locate Relevant Notes",
            "readOnlyHint": True,
            "openWorldHint": False,
        },
        "keywords": [
            "find",
            "locate",
            "source",
            "citation",
            "reference",
            "note",
            "folder",
            "where",
            "matching",
            "snippets",
        ],
    },
    {
        "name": "list_folders",
        "title": "List Folders",
        "description": (
            "List the user's folders from the Notelite backend so an agent can "
            "understand workspace organization before choosing notes to inspect."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "Tenant/user scope for folders."},
                "skip": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
            },
            "required": ["user_id"],
        },
        "annotations": {
            "title": "List Folders",
            "readOnlyHint": True,
            "openWorldHint": False,
        },
        "keywords": ["folders", "workspace", "browse", "list", "navigation", "organization"],
    },
    {
        "name": "list_notes",
        "title": "List Notes",
        "description": (
            "List notes from the Notelite backend with optional folder, pinned, "
            "and text search filters. Returns metadata by default and can include "
            "full note content when explicitly requested."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "Tenant/user scope for notes."},
                "folder_id": {"type": "string", "description": "Optional folder filter."},
                "pinned_only": {"type": "boolean", "default": False},
                "search": {"type": "string", "description": "Optional backend note search query."},
                "skip": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                "include_content": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include content and content_text in results.",
                },
            },
            "required": ["user_id"],
        },
        "annotations": {
            "title": "List Notes",
            "readOnlyHint": True,
            "openWorldHint": False,
        },
        "keywords": ["notes", "browse", "list", "folder", "pinned", "metadata", "content"],
    },
    {
        "name": "summarize_notes",
        "title": "Summarize Notes",
        "description": (
            "Return indexed summaries for specific notes, or first retrieve notes "
            "for a query and then return summaries plus optional evidence snippets."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "Tenant/user scope for summaries."},
                "note_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional note ids to summarize directly.",
                },
                "query": {
                    "type": "string",
                    "description": "Optional information need used to discover relevant notes first.",
                },
                "k": {"type": "integer", "minimum": 1, "maximum": 50, "default": 8},
                "include_context": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include bounded retrieved context previews when query-based summarization is used.",
                },
            },
            "required": ["user_id"],
        },
        "annotations": {
            "title": "Summarize Notes",
            "readOnlyHint": True,
            "openWorldHint": False,
        },
        "keywords": ["summary", "summarize", "notes", "overview", "digest", "explain", "brief"],
    },
]


_TOOL_CATALOG.extend(
    [
        {
            "name": "get_note",
            "title": "Get Note",
            "description": "Fetch one Notelite note by id, including content when requested.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "Tenant/user scope for notes."},
                    "note_id": {"type": "string", "description": "Note id to inspect."},
                    "include_content": {"type": "boolean", "default": True},
                },
                "required": ["user_id", "note_id"],
            },
            "annotations": {"title": "Get Note", "readOnlyHint": True, "openWorldHint": False},
            "keywords": ["get", "open", "read", "inspect", "note", "content", "details"],
        },
        {
            "name": "get_folder",
            "title": "Get Folder",
            "description": "Fetch one Notelite folder by id.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "Tenant/user scope for folders."},
                    "folder_id": {"type": "string", "description": "Folder id to inspect."},
                },
                "required": ["user_id", "folder_id"],
            },
            "annotations": {"title": "Get Folder", "readOnlyHint": True, "openWorldHint": False},
            "keywords": ["get", "open", "inspect", "folder", "details"],
        },
        {
            "name": "create_note",
            "title": "Create Note",
            "description": "Create a Notelite note in a folder. The backend queues ingestion for non-empty content.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "folder_id": {"type": "string"},
                    "title": {"type": "string"},
                    "content_text": {"type": "string", "default": ""},
                    "description": {"type": "string"},
                    "is_pinned": {"type": "boolean", "default": False},
                    "is_memory_included": {"type": "boolean", "default": False},
                },
                "required": ["user_id", "folder_id", "title"],
            },
            "annotations": {"title": "Create Note", "readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
            "keywords": ["create", "add", "write", "save", "new", "note"],
        },
        {
            "name": "update_note",
            "title": "Update Note",
            "description": "Update note title, description, folder, flags, or full text content. Content changes trigger re-ingestion.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "note_id": {"type": "string"},
                    "title": {"type": "string"},
                    "content_text": {"type": "string"},
                    "description": {"type": "string"},
                    "folder_id": {"type": "string"},
                    "is_pinned": {"type": "boolean"},
                    "is_memory_included": {"type": "boolean"},
                },
                "required": ["user_id", "note_id"],
            },
            "annotations": {"title": "Update Note", "readOnlyHint": False, "destructiveHint": True, "openWorldHint": False},
            "keywords": ["update", "edit", "rename", "pin", "unpin", "memory", "note", "content"],
        },
        {
            "name": "move_note",
            "title": "Move Note",
            "description": "Move a note to another folder and re-index its folder metadata.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "note_id": {"type": "string"},
                    "folder_id": {"type": "string"},
                },
                "required": ["user_id", "note_id", "folder_id"],
            },
            "annotations": {"title": "Move Note", "readOnlyHint": False, "destructiveHint": True, "openWorldHint": False},
            "keywords": ["move", "relocate", "folder", "note"],
        },
        {
            "name": "delete_note",
            "title": "Delete Note",
            "description": "Delete a note and queue removal from the vector index.",
            "inputSchema": {
                "type": "object",
                "properties": {"user_id": {"type": "string"}, "note_id": {"type": "string"}},
                "required": ["user_id", "note_id"],
            },
            "annotations": {"title": "Delete Note", "readOnlyHint": False, "destructiveHint": True, "openWorldHint": False},
            "keywords": ["delete", "remove", "trash", "note"],
        },
        {
            "name": "create_folder",
            "title": "Create Folder",
            "description": "Create a Notelite folder for the runtime user.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "name": {"type": "string"},
                    "is_pinned": {"type": "boolean", "default": False},
                },
                "required": ["user_id", "name"],
            },
            "annotations": {"title": "Create Folder", "readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
            "keywords": ["create", "add", "new", "folder", "workspace"],
        },
        {
            "name": "update_folder",
            "title": "Update Folder",
            "description": "Rename or pin/unpin a Notelite folder.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "folder_id": {"type": "string"},
                    "name": {"type": "string"},
                    "is_pinned": {"type": "boolean"},
                },
                "required": ["user_id", "folder_id"],
            },
            "annotations": {"title": "Update Folder", "readOnlyHint": False, "destructiveHint": True, "openWorldHint": False},
            "keywords": ["update", "rename", "pin", "unpin", "folder"],
        },
        {
            "name": "delete_folder",
            "title": "Delete Folder",
            "description": "Delete a folder and queue vector-index deletion for child notes.",
            "inputSchema": {
                "type": "object",
                "properties": {"user_id": {"type": "string"}, "folder_id": {"type": "string"}},
                "required": ["user_id", "folder_id"],
            },
            "annotations": {"title": "Delete Folder", "readOnlyHint": False, "destructiveHint": True, "openWorldHint": False},
            "keywords": ["delete", "remove", "folder", "workspace"],
        },
    ]
)

_TOOL_CATALOG.extend(
    [
        {
            "name": "list_tags",
            "title": "List Tags",
            "description": "List the user's Notelite tags.",
            "inputSchema": {"type": "object", "properties": {"user_id": {"type": "string"}}, "required": ["user_id"]},
            "annotations": {"title": "List Tags", "readOnlyHint": True, "openWorldHint": False},
            "keywords": ["tags", "labels", "list", "browse"],
        },
        {
            "name": "create_tag",
            "title": "Create Tag",
            "description": "Create a Notelite tag.",
            "inputSchema": {"type": "object", "properties": {"user_id": {"type": "string"}, "name": {"type": "string"}}, "required": ["user_id", "name"]},
            "annotations": {"title": "Create Tag", "readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
            "keywords": ["create", "add", "new", "tag", "label"],
        },
        {
            "name": "update_tag",
            "title": "Update Tag",
            "description": "Rename a Notelite tag.",
            "inputSchema": {"type": "object", "properties": {"user_id": {"type": "string"}, "tag_id": {"type": "string"}, "name": {"type": "string"}}, "required": ["user_id", "tag_id", "name"]},
            "annotations": {"title": "Update Tag", "readOnlyHint": False, "destructiveHint": True, "openWorldHint": False},
            "keywords": ["rename", "update", "tag", "label"],
        },
        {
            "name": "delete_tag",
            "title": "Delete Tag",
            "description": "Delete a Notelite tag.",
            "inputSchema": {"type": "object", "properties": {"user_id": {"type": "string"}, "tag_id": {"type": "string"}}, "required": ["user_id", "tag_id"]},
            "annotations": {"title": "Delete Tag", "readOnlyHint": False, "destructiveHint": True, "openWorldHint": False},
            "keywords": ["delete", "remove", "tag", "label"],
        },
        {
            "name": "add_tag_to_note",
            "title": "Add Tag To Note",
            "description": "Attach an existing tag to an existing note.",
            "inputSchema": {"type": "object", "properties": {"user_id": {"type": "string"}, "note_id": {"type": "string"}, "tag_id": {"type": "string"}}, "required": ["user_id", "note_id", "tag_id"]},
            "annotations": {"title": "Add Tag To Note", "readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
            "keywords": ["add", "attach", "tag", "label", "note"],
        },
        {
            "name": "remove_tag_from_note",
            "title": "Remove Tag From Note",
            "description": "Remove a tag association from a note.",
            "inputSchema": {"type": "object", "properties": {"user_id": {"type": "string"}, "note_id": {"type": "string"}, "tag_id": {"type": "string"}}, "required": ["user_id", "note_id", "tag_id"]},
            "annotations": {"title": "Remove Tag From Note", "readOnlyHint": False, "destructiveHint": True, "openWorldHint": False},
            "keywords": ["remove", "detach", "tag", "label", "note"],
        },
    ]
)


def _require_query(query: str) -> str:
    value = str(query or "").strip()
    if not value:
        raise ValueError("query is required")
    return value


def _require_user_id(user_id: str) -> str:
    value = str(user_id or "").strip()
    if not value:
        raise ValueError("user_id is required")
    return value


def _bounded_k(k: int, default: int) -> int:
    try:
        value = int(k)
    except (TypeError, ValueError):
        value = default
    return max(1, min(50, value))


def _history_items(history: Sequence[Mapping[str, Any]] | None) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for message in history or []:
        if not isinstance(message, Mapping):
            continue
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        items.append(
            {
                "role": str(message.get("role") or "user"),
                "content": content,
            }
        )
    return items


def _backend_api_base(backend_base_url: str | None = None) -> str:
    configured = (
        backend_base_url
        or os.getenv("NOTELITE_BACKEND_API_BASE")
        or os.getenv("BACKEND_API_BASE")
        or "http://localhost:8000/api"
    )
    return str(configured).rstrip("/")


_backend_http: httpx.Client | None = None
_backend_http_base: str | None = None


def _backend_service_base(backend_base_url: str | None = None) -> str:
    configured = backend_base_url or os.getenv("NOTELITE_BACKEND_API_BASE") or os.getenv("BACKEND_API_BASE")
    if not configured:
        try:
            from app.core.config import BACKEND_INTERNAL_URL_BASE

            configured = BACKEND_INTERNAL_URL_BASE
        except Exception:
            configured = "http://localhost:8000/api"
    base = str(configured).rstrip("/")
    for suffix in ("/conversations/internal", "/conversations"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    if not base.endswith("/api") and "/api/" not in base:
        base = f"{base}/api"
    return base.rstrip("/")


def _backend_client() -> httpx.Client:
    global _backend_http, _backend_http_base
    base = _backend_service_base()
    if _backend_http is None or _backend_http_base != base:
        _backend_http = httpx.Client(base_url=base, timeout=20.0)
        _backend_http_base = base
    return _backend_http


def _backend_headers(user_id: str) -> dict[str, str]:
    from app.core.config import AGENT_API_KEY
    from app.logger import get_trace_id

    headers = {
        "X-Internal-Key": AGENT_API_KEY,
        "X-User-Id": _require_user_id(user_id),
        "Content-Type": "application/json",
    }
    trace_id = get_trace_id()
    if trace_id:
        headers["X-Trace-Id"] = trace_id
    return headers


def _compact_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in payload.items() if value is not None}


def _backend_request(
    method: str,
    path: str,
    *,
    user_id: str,
    json_body: Mapping[str, Any] | None = None,
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        response = _backend_client().request(
            method,
            path,
            headers=_backend_headers(user_id),
            json=dict(json_body or {}) if json_body is not None else None,
            params=_compact_payload(params or {}),
            timeout=20.0,
        )
        response.raise_for_status()
        body = response.json()
    except httpx.HTTPStatusError as exc:
        detail: Any
        try:
            detail = exc.response.json()
        except ValueError:
            detail = exc.response.text
        return {
            "ok": False,
            "status_code": exc.response.status_code,
            "error": f"Backend {method} {path} failed",
            "detail": detail,
        }
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"Backend {method} {path} failed", "detail": str(exc)}

    if not isinstance(body, Mapping):
        return {"ok": False, "error": f"Backend {method} {path} returned a non-object response"}
    return {
        "ok": True,
        "data": body.get("data"),
        "message": body.get("message"),
        "status_code": response.status_code,
    }


def _note_from_backend_response(response: dict[str, Any], *, include_content: bool = True) -> dict[str, Any]:
    if not response.get("ok"):
        return response
    note = response.get("data") or {}
    return {
        "ok": True,
        "note": _public_note(note, include_content=include_content) if isinstance(note, Mapping) else note,
        "message": response.get("message"),
    }


def _folder_from_backend_response(response: dict[str, Any]) -> dict[str, Any]:
    if not response.get("ok"):
        return response
    return {"ok": True, "folder": response.get("data"), "message": response.get("message")}


def _tiptap_doc_from_text(text: str | None) -> dict[str, Any]:
    lines = str(text or "").splitlines() or [""]
    paragraphs: list[dict[str, Any]] = []
    for line in lines:
        paragraph: dict[str, Any] = {"type": "paragraph"}
        if line:
            paragraph["content"] = [{"type": "text", "text": line}]
        paragraphs.append(paragraph)
    return {"type": "doc", "content": paragraphs}


def _clamped_limit(limit: int, default: int = 50) -> int:
    try:
        value = int(limit or default)
    except (TypeError, ValueError):
        value = default
    return max(1, min(200, value))


def _json_ready(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.isoformat() if hasattr(value, "isoformat") else value
        for key, value in row.items()
    }


def _public_note(note: Mapping[str, Any], *, include_content: bool) -> dict[str, Any]:
    hidden = set() if include_content else {"content", "content_text"}
    public: dict[str, Any] = {}
    for key, value in note.items():
        key_str = str(key)
        if key_str in hidden:
            continue
        if key_str in {"content", "content_text"} and isinstance(value, str):
            public[key_str] = _chunk_preview(value, 1200)
            public[f"{key_str}_truncated"] = len(value) > 1200
        else:
            public[key_str] = value
    return public


def _summaries_for_notes(user_id: str, note_ids: Sequence[str] | None, limit: int) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from app.db.models import DocumentRecord
    from app.db.postgres import DatabaseManager

    stmt = (
        select(DocumentRecord)
        .where(DocumentRecord.user_id == _require_user_id(user_id))
        .where(DocumentRecord.summary != "")
        .order_by(DocumentRecord.updated_at.desc())
        .limit(_bounded_k(limit, 10))
    )
    normalized_note_ids = [str(note_id).strip() for note_id in note_ids or [] if str(note_id).strip()]
    if normalized_note_ids:
        stmt = stmt.where(DocumentRecord.note_id.in_(normalized_note_ids))

    with DatabaseManager.get_session_factory()() as session:
        rows = list(session.execute(stmt).scalars().all())

    return [
        {
            "doc_id": row.doc_id,
            "user_id": row.user_id,
            "folder_id": row.folder_id,
            "note_id": row.note_id,
            "summary": _chunk_preview(row.summary, 2000),
            "summary_truncated": len(row.summary or "") > 2000,
            "summary_generated_at": row.summary_generated_at.isoformat() if row.summary_generated_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        for row in rows
    ]


def _run_note_retrieval(
    *,
    query: str,
    user_id: str,
    k: int,
    role: str,
    history: Sequence[Mapping[str, Any]] | None,
) -> Any:
    from app.services.chat.retriever import retrieve_context_result
    from app.services.ingestion.storage.vector_store import QdrantVectorStore

    return retrieve_context_result(
        QdrantVectorStore(),
        _require_query(query),
        _require_user_id(user_id),
        _bounded_k(k, 12),
        str(role or "user"),
        _history_items(history),
    )


def _chunk_preview(text: str, max_chars: int = 700) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[: max_chars - 1].rstrip()}..."


def _note_evidence(reference: Mapping[str, Any]) -> dict[str, Any]:
    chunks = list(reference.get("chunks") or [])
    seed_scores = [
        float(chunk["score"])
        for chunk in chunks
        if isinstance(chunk, Mapping) and chunk.get("score") is not None
    ]
    best_score = max(seed_scores) if seed_scores else None
    return {
        "note_id": reference.get("note_id", ""),
        "folder_id": reference.get("folder_id", ""),
        "title": reference.get("title", "Untitled"),
        "folder": reference.get("folder", ""),
        "best_score": best_score,
        "chunk_ids": list(reference.get("chunk_ids") or []),
        "chunks": [
            {
                "chunk_id": chunk.get("chunk_id", ""),
                "doc_id": chunk.get("doc_id", ""),
                "chunk_index": chunk.get("chunk_index"),
                "total_chunks": chunk.get("total_chunks"),
                "chunk_type": chunk.get("chunk_type", ""),
                "is_seed": bool(chunk.get("is_seed")),
                "score": chunk.get("score"),
                "keywords": chunk.get("keywords") or [],
                "entities": chunk.get("entities") or [],
                "snippet": _chunk_preview(chunk.get("text", ""), 700),
                "text_truncated": len(str(chunk.get("text", ""))) > 700,
            }
            for chunk in chunks
            if isinstance(chunk, Mapping)
        ],
    }


def _note_location(reference: Mapping[str, Any]) -> dict[str, Any]:
    evidence = _note_evidence(reference)
    snippets = [
        _chunk_preview(chunk.get("snippet", ""), 360)
        for chunk in evidence["chunks"][:3]
        if chunk.get("snippet")
    ]
    keywords = sorted(
        {
            str(keyword)
            for chunk in evidence["chunks"]
            for keyword in (chunk.get("keywords") or [])
            if keyword
        }
    )
    entities = sorted(
        {
            str(entity)
            for chunk in evidence["chunks"]
            for entity in (chunk.get("entities") or [])
            if entity
        }
    )
    return {
        "note_id": evidence["note_id"],
        "folder_id": evidence["folder_id"],
        "title": evidence["title"],
        "folder": evidence["folder"],
        "best_score": evidence["best_score"],
        "chunk_ids": evidence["chunk_ids"],
        "match_count": len(evidence["chunks"]),
        "snippets": snippets,
        "keywords": keywords[:25],
        "entities": entities[:25],
    }


def _tool_score(query: str, tool: Mapping[str, Any]) -> float:
    terms = set(re.findall(r"[a-z0-9_]+", query.casefold()))
    if not terms:
        return 0.0

    searchable = " ".join(
        [
            str(tool.get("name", "")),
            str(tool.get("title", "")),
            str(tool.get("description", "")),
            " ".join(str(keyword) for keyword in tool.get("keywords") or []),
        ]
    ).casefold()
    searchable_terms = set(re.findall(r"[a-z0-9_]+", searchable))
    overlap = len(terms & searchable_terms)
    phrase_bonus = 1.0 if query.casefold() in searchable else 0.0
    return min(1.0, (overlap / math.sqrt(len(terms) + 1)) + phrase_bonus)


@mcp.tool()
def semantic_tool_search(query: str, limit: int = 8) -> dict[str, Any]:
    """Discover high-level Notelite capabilities relevant to an agent task."""
    search_query = _require_query(query)
    max_results = _bounded_k(limit, 8)
    scored = sorted(
        (
            {
                "score": _tool_score(search_query, tool),
                "payload": {
                    key: value
                    for key, value in tool.items()
                    if key != "keywords"
                },
            }
            for tool in _TOOL_CATALOG
        ),
        key=lambda item: item["score"],
        reverse=True,
    )
    return {"ok": True, "query": search_query, "tools": scored[:max_results]}


@mcp.tool()
def search_notes(
    query: str,
    user_id: str,
    k: int = 12,
    role: str = "user",
    history: list[dict[str, Any]] | None = None,
    include_context: bool = False,
    include_diagnostics: bool = False,
) -> dict[str, Any]:
    """Gather answer-ready evidence from notes using the full retrieval pipeline."""
    result = _run_note_retrieval(
        query=query,
        user_id=user_id,
        k=k,
        role=role,
        history=history,
    )
    response: dict[str, Any] = {
        "ok": True,
        "query": _require_query(query),
        "user_id": _require_user_id(user_id),
        "notes": [_note_evidence(reference) for reference in result.references],
        "events": result.events[:25] if isinstance(result.events, list) else result.events,
    }
    if include_context:
        response["context_texts"] = [_chunk_preview(text, 900) for text in list(result.context_texts or [])[: _bounded_k(k, 12)]]
    if include_diagnostics:
        response["diagnostics"] = result.diagnostics
    return response


@mcp.tool()
def locate_notes(
    query: str,
    user_id: str,
    k: int = 10,
    role: str = "user",
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Find relevant note locations and snippets without asking the LLM to answer."""
    result = _run_note_retrieval(
        query=query,
        user_id=user_id,
        k=k,
        role=role,
        history=history,
    )
    return {
        "ok": True,
        "query": _require_query(query),
        "user_id": _require_user_id(user_id),
        "notes": [_note_location(reference) for reference in result.references],
        "events": result.events[:25] if isinstance(result.events, list) else result.events,
    }


@mcp.tool()
def list_folders(
    user_id: str,
    skip: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """List folders for a server-authenticated user scope."""
    response = _backend_request(
        "GET",
        "/folders/internal/",
        user_id=user_id,
        params={"skip": max(0, int(skip or 0)), "limit": _clamped_limit(limit)},
    )
    if not response.get("ok"):
        return response
    return {"ok": True, "folders": response.get("data") or [], "message": response.get("message")}


@mcp.tool()
def list_notes(
    user_id: str,
    folder_id: str | None = None,
    pinned_only: bool = False,
    search: str | None = None,
    skip: int = 0,
    limit: int = 50,
    include_content: bool = False,
) -> dict[str, Any]:
    """List notes for a server-authenticated user scope with optional filters."""
    response = _backend_request(
        "GET",
        "/notes/internal/",
        user_id=user_id,
        params={
            "folder_id": folder_id,
            "pinned_only": bool(pinned_only),
            "search": search,
            "skip": max(0, int(skip or 0)),
            "limit": _clamped_limit(limit),
        },
    )
    if not response.get("ok"):
        return response
    notes = [
        _public_note(note, include_content=include_content)
        for note in (response.get("data") or [])
        if isinstance(note, Mapping)
    ]
    return {"ok": True, "notes": notes, "message": response.get("message")}


@mcp.tool()
def summarize_notes(
    user_id: str,
    note_ids: list[str] | None = None,
    query: str | None = None,
    k: int = 8,
    include_context: bool = False,
) -> dict[str, Any]:
    """Return indexed note summaries, optionally after retrieving query-relevant notes."""
    selected_note_ids = [str(note_id).strip() for note_id in note_ids or [] if str(note_id).strip()]
    retrieval = None
    if query and not selected_note_ids:
        retrieval = _run_note_retrieval(
            query=query,
            user_id=user_id,
            k=k,
            role="user",
            history=None,
        )
        selected_note_ids = [
            str(reference.get("note_id") or "")
            for reference in retrieval.references
            if reference.get("note_id")
        ]

    summaries = _summaries_for_notes(user_id, selected_note_ids or None, _bounded_k(k, 8))
    response: dict[str, Any] = {
        "ok": True,
        "user_id": _require_user_id(user_id),
        "note_ids": selected_note_ids,
        "summaries": summaries,
    }
    if retrieval is not None:
        response["events"] = retrieval.events[:25] if isinstance(retrieval.events, list) else retrieval.events
        response["notes"] = [_note_location(reference) for reference in retrieval.references]
        if include_context:
            response["context_texts"] = [_chunk_preview(text, 900) for text in list(retrieval.context_texts or [])[: _bounded_k(k, 8)]]
    return response


@mcp.tool()
def get_note(user_id: str, note_id: str, include_content: bool = True) -> dict[str, Any]:
    """Fetch one note by id through the backend internal API."""
    response = _backend_request("GET", f"/notes/internal/{str(note_id).strip()}", user_id=user_id)
    return _note_from_backend_response(response, include_content=include_content)


@mcp.tool()
def get_folder(user_id: str, folder_id: str) -> dict[str, Any]:
    """Fetch one folder by id through the backend internal API."""
    response = _backend_request("GET", f"/folders/internal/{str(folder_id).strip()}", user_id=user_id)
    return _folder_from_backend_response(response)


@mcp.tool()
def create_note(
    user_id: str,
    folder_id: str,
    title: str,
    content_text: str = "",
    description: str | None = None,
    is_pinned: bool = False,
    is_memory_included: bool = False,
) -> dict[str, Any]:
    """Create a note through the backend so ownership checks and ingestion dispatch run."""
    payload = {
        "title": str(title or "").strip(),
        "folder_id": str(folder_id).strip(),
        "description": description,
        "content": _tiptap_doc_from_text(content_text),
        "is_pinned": bool(is_pinned),
        "is_memory_included": bool(is_memory_included),
    }
    if not payload["title"]:
        return {"ok": False, "error": "title is required"}
    response = _backend_request("POST", "/notes/internal/", user_id=user_id, json_body=_compact_payload(payload))
    return _note_from_backend_response(response, include_content=True)


@mcp.tool()
def update_note(
    user_id: str,
    note_id: str,
    title: str | None = None,
    content_text: str | None = None,
    description: str | None = None,
    folder_id: str | None = None,
    is_pinned: bool | None = None,
    is_memory_included: bool | None = None,
) -> dict[str, Any]:
    """Update a note through the backend so versioning and ingestion dispatch run."""
    payload: dict[str, Any] = {
        "title": str(title).strip() if title is not None else None,
        "description": description,
        "folder_id": str(folder_id).strip() if folder_id else None,
        "is_pinned": is_pinned,
        "is_memory_included": is_memory_included,
    }
    if content_text is not None:
        payload["content"] = _tiptap_doc_from_text(content_text)
    payload = _compact_payload(payload)
    if not payload:
        return {"ok": False, "error": "at least one update field is required"}
    response = _backend_request("PATCH", f"/notes/internal/{str(note_id).strip()}", user_id=user_id, json_body=payload)
    return _note_from_backend_response(response, include_content=True)


@mcp.tool()
def move_note(user_id: str, note_id: str, folder_id: str) -> dict[str, Any]:
    """Move a note through the backend and re-index folder metadata."""
    response = _backend_request(
        "PATCH",
        f"/notes/internal/{str(note_id).strip()}/move",
        user_id=user_id,
        json_body={"folder_id": str(folder_id).strip()},
    )
    return _note_from_backend_response(response, include_content=False)


@mcp.tool()
def delete_note(user_id: str, note_id: str) -> dict[str, Any]:
    """Delete a note through the backend and queue vector-index cleanup."""
    return _backend_request("DELETE", f"/notes/internal/{str(note_id).strip()}", user_id=user_id)


@mcp.tool()
def create_folder(user_id: str, name: str, is_pinned: bool = False) -> dict[str, Any]:
    """Create a folder through the backend internal API."""
    folder_name = str(name or "").strip()
    if not folder_name:
        return {"ok": False, "error": "name is required"}
    response = _backend_request(
        "POST",
        "/folders/internal/",
        user_id=user_id,
        json_body={"name": folder_name, "is_pinned": bool(is_pinned)},
    )
    return _folder_from_backend_response(response)


@mcp.tool()
def update_folder(
    user_id: str,
    folder_id: str,
    name: str | None = None,
    is_pinned: bool | None = None,
) -> dict[str, Any]:
    """Rename or pin/unpin a folder through the backend internal API."""
    payload = _compact_payload(
        {
            "name": str(name).strip() if name is not None else None,
            "is_pinned": is_pinned,
        }
    )
    if not payload:
        return {"ok": False, "error": "at least one update field is required"}
    response = _backend_request("PATCH", f"/folders/internal/{str(folder_id).strip()}", user_id=user_id, json_body=payload)
    return _folder_from_backend_response(response)


@mcp.tool()
def delete_folder(user_id: str, folder_id: str) -> dict[str, Any]:
    """Delete a folder through the backend and queue cleanup for child notes."""
    return _backend_request("DELETE", f"/folders/internal/{str(folder_id).strip()}", user_id=user_id)


@mcp.tool()
def list_tags(user_id: str) -> dict[str, Any]:
    """List tags through the backend internal API."""
    response = _backend_request("GET", "/tags/internal/", user_id=user_id)
    if not response.get("ok"):
        return response
    return {"ok": True, "tags": response.get("data") or [], "message": response.get("message")}


@mcp.tool()
def create_tag(user_id: str, name: str) -> dict[str, Any]:
    """Create a tag through the backend internal API."""
    tag_name = str(name or "").strip()
    if not tag_name:
        return {"ok": False, "error": "name is required"}
    response = _backend_request("POST", "/tags/internal/", user_id=user_id, json_body={"name": tag_name})
    if not response.get("ok"):
        return response
    return {"ok": True, "tag": response.get("data"), "message": response.get("message")}


@mcp.tool()
def update_tag(user_id: str, tag_id: str, name: str) -> dict[str, Any]:
    """Rename a tag through the backend internal API."""
    tag_name = str(name or "").strip()
    if not tag_name:
        return {"ok": False, "error": "name is required"}
    response = _backend_request(
        "PATCH",
        f"/tags/internal/{str(tag_id).strip()}",
        user_id=user_id,
        json_body={"name": tag_name},
    )
    if not response.get("ok"):
        return response
    return {"ok": True, "tag": response.get("data"), "message": response.get("message")}


@mcp.tool()
def delete_tag(user_id: str, tag_id: str) -> dict[str, Any]:
    """Delete a tag through the backend internal API."""
    return _backend_request("DELETE", f"/tags/internal/{str(tag_id).strip()}", user_id=user_id)


@mcp.tool()
def add_tag_to_note(user_id: str, note_id: str, tag_id: str) -> dict[str, Any]:
    """Attach an existing tag to an existing note through the backend."""
    return _backend_request(
        "POST",
        f"/notes/internal/{str(note_id).strip()}/tags/{str(tag_id).strip()}",
        user_id=user_id,
    )


@mcp.tool()
def remove_tag_from_note(user_id: str, note_id: str, tag_id: str) -> dict[str, Any]:
    """Remove a tag association from a note through the backend."""
    return _backend_request(
        "DELETE",
        f"/notes/internal/{str(note_id).strip()}/tags/{str(tag_id).strip()}",
        user_id=user_id,
    )


if __name__ == "__main__":
    # export MCP_URL=http://127.0.0.1:8000/mcp
    print("starting mcp...")
    mcp.run(transport="streamable-http")
