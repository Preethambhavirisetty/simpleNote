from __future__ import annotations

import importlib
import os
import math
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
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


from app.mcp import analysis

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

_TOOL_CATALOG.extend(
    [
        {
            "name": "count_note_mentions",
            "title": "Count Mentions",
            "description": (
                "Count how many notes and passages mention a topic, and whether it "
                "appears at all. Use for 'how many times did I mention X' and "
                "'did I ever write about X' - questions a top-k search cannot answer, "
                "because it returns k results whether or not they are relevant."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Topic to count."},
                    "user_id": {"type": "string"},
                    "k": {"type": "integer", "minimum": 1, "maximum": 50, "default": 50},
                    "role": {"type": "string", "enum": ["user", "admin"], "default": "user"},
                },
                "required": ["query", "user_id"],
            },
            "annotations": {"title": "Count Mentions", "readOnlyHint": True, "openWorldHint": False},
            "keywords": ["count", "how many", "times", "mention", "ever", "did i", "frequency"],
        },
        {
            "name": "notes_in_period",
            "title": "Notes In Period",
            "description": (
                "List notes from a date range, either by when they were written or by "
                "dates their text refers to. Use for 'what did I write in January 2025'. "
                "The two bases differ: a note written in January can be about March."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "start_date": {"type": "string", "description": "ISO date, inclusive."},
                    "end_date": {"type": "string", "description": "ISO date, inclusive."},
                    "basis": {
                        "type": "string",
                        "enum": ["written", "about", "either"],
                        "default": "written",
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                },
                "required": ["user_id", "start_date", "end_date"],
            },
            "annotations": {"title": "Notes In Period", "readOnlyHint": True, "openWorldHint": False},
            "keywords": ["date", "range", "month", "year", "january", "period", "between", "wrote"],
        },
        {
            "name": "last_mention",
            "title": "Last Mention",
            "description": (
                "When a topic was most recently written about, and in which note. Use "
                "for 'when did I last write about X'. Reports both the note's last edit "
                "and the latest date the text refers to."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "user_id": {"type": "string"},
                    "role": {"type": "string", "enum": ["user", "admin"], "default": "user"},
                },
                "required": ["query", "user_id"],
            },
            "annotations": {"title": "Last Mention", "readOnlyHint": True, "openWorldHint": False},
            "keywords": ["when", "last", "recent", "latest", "most recently", "date"],
        },
        {
            "name": "related_notes",
            "title": "Related Notes",
            "description": (
                "Notes related to the notes about a topic - a second hop that searches "
                "using the seed notes' own vocabulary, surfacing neighbours that never "
                "use the original word. Use for 'notes related to the ones about X'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "user_id": {"type": "string"},
                    "k": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                    "role": {"type": "string", "enum": ["user", "admin"], "default": "user"},
                },
                "required": ["query", "user_id"],
            },
            "annotations": {"title": "Related Notes", "readOnlyHint": True, "openWorldHint": False},
            "keywords": ["related", "similar", "connected", "like", "associated", "neighbours"],
        },
        {
            "name": "recent_mentions",
            "title": "Recent Mentions",
            "description": (
                "A topic restricted to a recent time window, newest first. Use for "
                "'what food did I eat recently' or 'where did I go recently'. Reports "
                "how many matches fell outside the window, so 'nothing recently' can be "
                "distinguished from 'nothing at all'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "user_id": {"type": "string"},
                    "days": {"type": "integer", "minimum": 1, "maximum": 365, "default": 30},
                    "k": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
                    "role": {"type": "string", "enum": ["user", "admin"], "default": "user"},
                },
                "required": ["query", "user_id"],
            },
            "annotations": {"title": "Recent Mentions", "readOnlyHint": True, "openWorldHint": False},
            "keywords": ["recently", "lately", "past week", "last month", "recent", "these days"],
        },
    ]
)

# A retriever returns its k best passages whether or not any of them are about
# the question, so "did I ever mention X" is always yes unless something
# rejects weak matches. Measured on this corpus: genuine topics score 1.3-5.7
# and unrelated ones 0.06-0.07, so a floor below the gap separates them.
#
# Calibrate with `MENTION_MIN_RELEVANCE` rather than editing this: the scores
# are cross-encoder logits whose scale depends on the reranker model, and the
# gap was measured on a small corpus.
MENTION_MIN_RELEVANCE = float(os.getenv("MENTION_MIN_RELEVANCE", "0.5"))


def _split_by_relevance(
    notes: Sequence[Mapping[str, Any]], min_relevance: float | None = None
) -> tuple[list[dict[str, Any]], int]:
    """Split notes into confident matches and a count of the weak ones."""
    floor = MENTION_MIN_RELEVANCE if min_relevance is None else float(min_relevance)
    confident = [note for note in notes if (note.get("best_score") or 0.0) >= floor]
    return list(confident), len(notes) - len(confident)

# A cross-encoder scores the whole query against the passage, so interrogative
# scaffolding drowns the topic: measured on this corpus, "food" scores 5.68
# against the food note and "how many times did I mention food" scores 0.05.
# These tools are invoked with the user's literal question, so the scaffolding
# is stripped before searching. Purely lexical - no model call, and the
# original question is still reported back.
_QUESTION_PREFIXES = re.compile(
    r"""^\s*(?:
        how\s+(?:many\s+times|often)\s+(?:did|have|do)\s+i(?:\s+ever)?
      | did\s+i\s+ever | have\s+i(?:\s+ever)?
      | when\s+did\s+i(?:\s+last)? | when\s+was\s+the\s+last\s+time\s+i
      | what\s+notes?\s+did\s+i | which\s+notes?\s+did\s+i
      | get\s+me\s+(?:all\s+)?notes?\s+related\s+to\s+the\s+ones?(?:\s+that)?\s+i
      | (?:get|show|give)\s+me(?:\s+all)? | tell\s+me
      | what | where | when | who
    )\b""",
    re.IGNORECASE | re.VERBOSE,
)
# Verbs of writing/mentioning carry no topic signal of their own.
_QUESTION_VERBS = re.compile(
    r"^\s*(?:did\s+i\s+)?(?:ever\s+)?"
    r"(?:mention(?:ed)?|write|wrote|written|talk(?:ed)?|say|said|note[ds]?)"
    r"(?:\s+about)?\b",
    re.IGNORECASE,
)
_LEADING_FILLER = re.compile(r"^\s*(?:about|regarding|related\s+to|any|the)\b", re.IGNORECASE)


def topic_from_question(question: str) -> str:
    """The searchable topic inside a question, or the question if none is found.

    "how many times did I mention going to a picnic" -> "going to a picnic"
    "when did I last write about books"              -> "books"

    Never returns empty: a question that is entirely scaffolding falls back to
    the original text rather than searching for nothing.
    """
    text = str(question or "").strip().rstrip("?").strip()
    if not text:
        return ""

    previous = None
    while previous != text:
        previous = text
        for pattern in (_QUESTION_PREFIXES, _QUESTION_VERBS, _LEADING_FILLER):
            text = pattern.sub("", text, count=1).strip()

    return text or str(question or "").strip().rstrip("?").strip()


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
    return {"ok": True, "query": search_query,
        "searched_for": topic, "tools": scored[:max_results]}


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


# ── Analytical tools ─────────────────────────────────────────────────────────
#
# Ranked retrieval answers "what is most relevant"; these answer "how many",
# "when", "did I ever", and "what else is like this". A top-k search cannot
# answer any of them honestly - asked for a count it returns k, and asked
# "did I ever" it always has a best guess.


@mcp.tool()
def count_note_mentions(
    query: str,
    user_id: str,
    k: int = 50,
    role: str = "user",
    min_relevance: float | None = None,
) -> dict[str, Any]:
    """Count how often a topic appears across notes, and whether it appears at all.

    Answers "how many times did I mention X" and "did I ever mention X".
    Returns note-level and passage-level counts plus the notes themselves, so
    the caller can state a number and cite it.
    """
    search_query = _require_query(query)
    topic = topic_from_question(search_query) or search_query
    scope = _require_user_id(user_id)
    result = _run_note_retrieval(
        query=topic, user_id=scope, k=_bounded_k(k, 50), role=role, history=None
    )

    ranked = [_note_location(reference) for reference in result.references]
    notes, weak = _split_by_relevance(ranked, min_relevance)
    mention_count = sum(note["match_count"] for note in notes)
    indexed = analysis.indexed_note_count(scope)

    return {
        "ok": True,
        "query": search_query,
        "searched_for": topic,
        "found": bool(notes),
        "note_count": len(notes),
        "mention_count": mention_count,
        # Retrieval returned these but they scored below the relevance floor.
        # Reported rather than hidden: a caller seeing 0 confident and 3 weak
        # can say "nothing clearly about that" instead of a flat "never".
        "weak_matches_excluded": weak,
        "min_relevance": MENTION_MIN_RELEVANCE if min_relevance is None else min_relevance,
        # Without this, "0 mentions" is indistinguishable from "nothing is
        # indexed yet", and the assistant would tell the user they never wrote
        # something they did write.
        "indexed_note_count": indexed,
        "searched_everything": len(notes) < _bounded_k(k, 50),
        "notes": [
            {
                "note_id": note["note_id"],
                "title": note["title"],
                "folder": note["folder"],
                "mentions": note["match_count"],
                "snippets": note["snippets"][:2],
            }
            for note in notes
        ],
    }


@mcp.tool()
def notes_in_period(
    user_id: str,
    start_date: str,
    end_date: str,
    basis: str = "written",
    limit: int = 50,
) -> dict[str, Any]:
    """List notes from a date range, by when they were written or what they are about.

    Answers "what notes did I write in January 2025". Dates are ISO
    (YYYY-MM-DD); `end_date` is inclusive of that whole day.

    `basis` picks which date is meant, and they are genuinely different:
      written - the note was created or edited in the range
      about   - the note's text refers to a date in the range, whenever it was
                written ("we fly to Boston on March 3rd")
      either  - either of the above
    """
    scope = _require_user_id(user_id)
    try:
        start, end = _parse_period(start_date, end_date)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    if basis not in ("written", "about", "either"):
        return {"ok": False, "error": "basis must be written, about, or either"}

    rows = analysis.notes_written_between(
        scope, start, end, basis=basis, limit=_clamped_limit(limit)
    )
    referenced = analysis.referenced_dates(scope, [row["doc_id"] for row in rows])
    dates_by_doc: dict[str, list[dict[str, Any]]] = {}
    for entry in referenced:
        dates_by_doc.setdefault(entry["doc_id"], []).append(
            {"date": analysis.iso(entry["date_value"]), "phrase": entry["date_text"]}
        )

    return {
        "ok": True,
        "start_date": analysis.iso(start),
        "end_date": analysis.iso(end),
        "basis": basis,
        "note_count": len(rows),
        "indexed_note_count": analysis.indexed_note_count(scope),
        "notes": [
            {
                "note_id": row["note_id"],
                "folder_id": row["folder_id"],
                "summary": _chunk_preview(row["summary"] or "", 400),
                "created_at": analysis.iso(row["created_at"]),
                "updated_at": analysis.iso(row["updated_at"]),
                "dates_mentioned": dates_by_doc.get(row["doc_id"], [])[:5],
            }
            for row in rows
        ],
    }


@mcp.tool()
def last_mention(query: str, user_id: str, role: str = "user") -> dict[str, Any]:
    """When a topic was most recently written about, and in which note.

    Answers "when did I last write about books". Reports both dates that apply:
    when the note was last edited, and the latest date its text refers to.
    """
    search_query = _require_query(query)
    topic = topic_from_question(search_query) or search_query
    scope = _require_user_id(user_id)
    result = _run_note_retrieval(
        query=topic, user_id=scope, k=10, role=role, history=None
    )
    notes, weak = _split_by_relevance(
        [_note_location(reference) for reference in result.references]
    )
    if not notes:
        return {
            "ok": True,
            "query": search_query,
        "searched_for": topic,
            "found": False,
            "weak_matches_excluded": weak,
            "indexed_note_count": analysis.indexed_note_count(scope),
        }

    doc_ids = [f"{scope}-{note['note_id']}" for note in notes]
    stamps = analysis.document_timestamps(scope, doc_ids)
    referenced = analysis.referenced_dates(scope, doc_ids, limit=20)

    dated = [
        (stamps[doc_id]["updated_at"], note)
        for doc_id, note in zip(doc_ids, notes)
        if doc_id in stamps and stamps[doc_id].get("updated_at")
    ]
    dated.sort(key=lambda item: item[0], reverse=True)
    latest_written, latest_note = dated[0] if dated else (None, notes[0])

    return {
        "ok": True,
        "query": search_query,
        "searched_for": topic,
        "found": True,
        "last_written_at": analysis.iso(latest_written),
        "note": {
            "note_id": latest_note["note_id"],
            "title": latest_note["title"],
            "folder": latest_note["folder"],
            "snippets": latest_note["snippets"][:2],
        },
        # The most recent date the matching notes talk about, which can differ
        # from when they were written.
        "latest_date_mentioned": (
            {
                "date": analysis.iso(referenced[0]["date_value"]),
                "phrase": referenced[0]["date_text"],
            }
            if referenced
            else None
        ),
        "other_notes": [
            {"note_id": note["note_id"], "title": note["title"]} for _, note in dated[1:5]
        ],
    }


@mcp.tool()
def related_notes(
    query: str,
    user_id: str,
    k: int = 10,
    role: str = "user",
) -> dict[str, Any]:
    """Find notes related to the notes about a topic - a second hop outward.

    Answers "get me all notes related to the ones I wrote about fun". The first
    hop finds seed notes for the topic; the second searches using what those
    notes are actually about (their summaries and keywords), which surfaces
    neighbours that never use the original word.
    """
    search_query = _require_query(query)
    topic = topic_from_question(search_query) or search_query
    scope = _require_user_id(user_id)
    limit = _bounded_k(k, 10)

    seeds = _run_note_retrieval(
        query=topic, user_id=scope, k=limit, role=role, history=None
    )
    seed_notes, _weak_seeds = _split_by_relevance(
        [_note_location(reference) for reference in seeds.references]
    )
    if not seed_notes:
        return {
            "ok": True,
            "query": search_query,
        "searched_for": topic,
            "seed_notes": [],
            "related_notes": [],
            "indexed_note_count": analysis.indexed_note_count(scope),
        }

    seed_ids = {note["note_id"] for note in seed_notes}
    # The second query is built from the seeds' own vocabulary rather than the
    # user's words, which is what makes this a different hop and not a rerun.
    expansion = " ".join(
        dict.fromkeys(
            [note["title"] for note in seed_notes]
            + [term for note in seed_notes for term in note["keywords"][:6]]
            + [term for note in seed_notes for term in note["entities"][:4]]
        )
    ).strip()

    neighbours = _run_note_retrieval(
        query=expansion or topic,
        user_id=scope,
        k=limit * 2,
        role=role,
        history=None,
    )
    related = [
        _note_location(reference)
        for reference in neighbours.references
        if reference.get("note_id") not in seed_ids
    ][:limit]

    return {
        "ok": True,
        "query": search_query,
        "searched_for": topic,
        "expansion_terms": expansion[:300],
        "seed_notes": [
            {"note_id": note["note_id"], "title": note["title"], "folder": note["folder"]}
            for note in seed_notes
        ],
        "related_notes": [
            {
                "note_id": note["note_id"],
                "title": note["title"],
                "folder": note["folder"],
                "score": note["best_score"],
                "snippets": note["snippets"][:1],
            }
            for note in related
        ],
    }


@mcp.tool()
def recent_mentions(
    query: str,
    user_id: str,
    days: int = 30,
    k: int = 20,
    role: str = "user",
) -> dict[str, Any]:
    """What a topic looked like recently - matches restricted to a time window.

    Answers "what food did I eat recently" and "where did I go recently":
    a topic search whose results are filtered to notes written in the window
    and ordered newest first, rather than by relevance alone.
    """
    search_query = _require_query(query)
    topic = topic_from_question(search_query) or search_query
    scope = _require_user_id(user_id)
    start, end = analysis.window_from_days(days)

    result = _run_note_retrieval(
        query=topic, user_id=scope, k=_bounded_k(k, 20), role=role, history=None
    )
    notes, _weak = _split_by_relevance(
        [_note_location(reference) for reference in result.references]
    )
    doc_ids = [f"{scope}-{note['note_id']}" for note in notes]
    stamps = analysis.document_timestamps(scope, doc_ids)

    within = []
    for doc_id, note in zip(doc_ids, notes):
        stamp = stamps.get(doc_id)
        updated = stamp.get("updated_at") if stamp else None
        if updated is None:
            continue
        # Compare in UTC: stored timestamps may be naive.
        moment = updated if updated.tzinfo else updated.replace(tzinfo=timezone.utc)
        if start <= moment <= end:
            within.append((moment, note))
    within.sort(key=lambda item: item[0], reverse=True)

    return {
        "ok": True,
        "query": search_query,
        "searched_for": topic,
        "days": days,
        "since": analysis.iso(start),
        "note_count": len(within),
        # Distinguishing these two lets the caller say "nothing in the last 30
        # days, though you wrote about it before" instead of "nothing found".
        "matched_before_window": len(notes) - len(within),
        "notes": [
            {
                "note_id": note["note_id"],
                "title": note["title"],
                "folder": note["folder"],
                "updated_at": analysis.iso(moment),
                "snippets": note["snippets"][:2],
            }
            for moment, note in within
        ],
    }


def _parse_period(start_date: str, end_date: str) -> tuple[datetime, datetime]:
    """Parse an inclusive ISO date range into a half-open UTC window."""
    try:
        start = datetime.fromisoformat(str(start_date).strip()).replace(tzinfo=timezone.utc)
        end = datetime.fromisoformat(str(end_date).strip()).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError("start_date and end_date must be ISO dates (YYYY-MM-DD)") from exc
    if end < start:
        raise ValueError("end_date must not be before start_date")
    # Callers mean "through the end of that day".
    return start, end + timedelta(days=1)


if __name__ == "__main__":
    # export MCP_URL=http://127.0.0.1:8000/mcp
    #
    # FastMCP binds 127.0.0.1 by default, which is unreachable from another
    # container. The default stays loopback for local runs; containers set
    # MCP_HOST=0.0.0.0.
    mcp.settings.host = os.getenv("MCP_HOST", "127.0.0.1")
    mcp.settings.port = int(os.getenv("MCP_PORT", "8000"))

    # The SDK's DNS-rebinding protection validates the Host header against
    # localhost only, so a call to http://agent-mcp:8000/mcp from another
    # container is rejected with 421. Name the hosts that may address this
    # server; MCP_ALLOWED_HOSTS keeps that a deployment decision.
    allowed = [
        host.strip()
        for host in os.getenv("MCP_ALLOWED_HOSTS", "").split(",")
        if host.strip()
    ]
    if allowed:
        from mcp.server.transport_security import TransportSecuritySettings

        mcp.settings.transport_security = TransportSecuritySettings(
            allowed_hosts=allowed,
            allowed_origins=allowed,
        )

    print(f"starting mcp on {mcp.settings.host}:{mcp.settings.port}...")
    mcp.run(transport="streamable-http")
