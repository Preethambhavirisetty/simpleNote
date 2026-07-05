from __future__ import annotations

import importlib
import os
import math
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
MCP_APP_ROOT = Path(__file__).resolve().parent
AGENT_ROOT = REPO_ROOT / "notelite_agent"


def _load_fastmcp() -> Any:
    """Load the installed MCP SDK despite this app directory also being named mcp."""
    original_path = list(sys.path)
    local_package = sys.modules.pop("mcp", None)
    blocked_paths = {REPO_ROOT, MCP_APP_ROOT}
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

if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))


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
    from sqlalchemy import text

    from app.db.postgres import DatabaseManager

    with DatabaseManager.get_session_factory()() as session:
        rows = session.execute(
            text(
                """
                SELECT id::text AS id, user_id::text AS user_id, name, is_pinned,
                       created_at, updated_at
                FROM folders
                WHERE user_id::text = :user_id
                ORDER BY is_pinned DESC, updated_at DESC
                OFFSET :skip
                LIMIT :limit
                """
            ),
            {"user_id": _require_user_id(user_id), "skip": max(0, int(skip or 0)), "limit": _clamped_limit(limit)},
        ).mappings().all()
    return {"ok": True, "folders": [_json_ready(dict(row)) for row in rows], "message": "Folders retrieved"}


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
    from sqlalchemy import text

    from app.db.postgres import DatabaseManager

    where = ["n.user_id::text = :user_id"]
    params: dict[str, Any] = {
        "user_id": _require_user_id(user_id),
        "skip": max(0, int(skip or 0)),
        "limit": _clamped_limit(limit),
    }
    if folder_id:
        where.append("n.folder_id::text = :folder_id")
        params["folder_id"] = str(folder_id)
    if pinned_only:
        where.append("n.is_pinned IS TRUE")
    if search:
        where.append("(n.title ILIKE :search OR coalesce(n.content_text, '') ILIKE :search)")
        params["search"] = f"%{search}%"

    query = text(
        f"""
        SELECT n.id::text AS id, n.user_id::text AS user_id, n.folder_id::text AS folder_id,
               n.title, coalesce(n.description, '') AS description, n.content_text,
               n.version, n.note_size, n.is_pinned, n.is_memory_included,
               n.created_at, n.updated_at, f.name AS folder
        FROM notes n
        JOIN folders f ON f.id = n.folder_id
        WHERE {' AND '.join(where)}
        ORDER BY n.is_pinned DESC, n.updated_at DESC
        OFFSET :skip
        LIMIT :limit
        """
    )
    with DatabaseManager.get_session_factory()() as session:
        rows = session.execute(query, params).mappings().all()
    notes = [_public_note(_json_ready(dict(row)), include_content=include_content) for row in rows]
    return {"ok": True, "notes": notes, "message": "Notes retrieved"}


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


if __name__ == "__main__":
    # export MCP_URL=http://127.0.0.1:8000/mcp
    print("starting mcp...")
    mcp.run(transport="streamable-http")
