"""A stand-in for orchestrator/app/mcp/main.py, for testing without infra.

The real MCP server needs Qdrant, Postgres, and the backend API. This one
serves the same tool names and response shapes over the real MCP
streamable-http transport, so the client, the handshake, and result decoding
are genuinely exercised - only the data is canned.

    .venv/bin/python -m evals.fake_mcp_server        # listens on :8200
    MCP_SERVERS=notelite=http://127.0.0.1:8200/mcp   # point the runtime at it
"""

from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Fake Notelite Tools")

NOTES = [
    {
        "note_id": "n-1",
        "title": "Vendor migration decision",
        "folder": "Work",
        "folder_id": "f-1",
        "best_score": 0.91,
        "updated_at": "2026-07-30T10:00:00Z",
        "chunks": [{"snippet": "We chose vendor B for the migration.", "score": 0.91}],
    },
    {
        "note_id": "n-2",
        "title": "Pricing model notes",
        "folder": "Work",
        "folder_id": "f-1",
        "best_score": 0.44,
        "updated_at": "2026-06-02T09:00:00Z",
        "chunks": [{"snippet": "Usage-based pricing beat seat-based.", "score": 0.44}],
    },
    {
        "note_id": "n-3",
        "title": "Undated scratch",
        "folder": "Inbox",
        "folder_id": "f-2",
        "best_score": 0.20,
        "chunks": [{"snippet": "todo: tidy this up", "score": 0.20}],
    },
]


@mcp.tool()
def search_notes(
    query: str,
    user_id: str,
    k: int = 12,
    role: str = "user",
    history: list[dict[str, Any]] | None = None,
    include_context: bool = False,
) -> dict[str, Any]:
    """Gather answer-ready evidence from notes."""
    return {"ok": True, "query": query, "user_id": user_id, "notes": NOTES[:k]}


@mcp.tool()
def locate_notes(
    query: str,
    user_id: str,
    k: int = 10,
    role: str = "user",
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Find relevant note locations."""
    return {"ok": True, "query": query, "notes": NOTES[:k]}


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
    """List notes with filters."""
    notes = [n for n in NOTES if folder_id is None or n["folder_id"] == folder_id]
    return {
        "ok": True,
        "notes": notes[skip : skip + limit],
        "echo_filters": {"folder_id": folder_id, "pinned_only": pinned_only, "search": search},
    }


@mcp.tool()
def list_folders(user_id: str, skip: int = 0, limit: int = 50) -> dict[str, Any]:
    """List folders."""
    return {
        "ok": True,
        "folders": [
            {"folder_id": "f-1", "name": "Work"},
            {"folder_id": "f-2", "name": "Inbox"},
        ],
    }


@mcp.tool()
def list_tags(user_id: str) -> dict[str, Any]:
    """List tags."""
    return {"ok": True, "tags": [{"tag_id": "t-1", "name": "research"}]}


@mcp.tool()
def get_note(user_id: str, note_id: str, include_content: bool = True) -> dict[str, Any]:
    """Fetch one note."""
    for note in NOTES:
        if note["note_id"] == note_id:
            return {"ok": True, "note": note}
    return {"ok": False, "error": f"note {note_id} not found"}


@mcp.tool()
def summarize_notes(
    user_id: str,
    note_ids: list[str] | None = None,
    query: str | None = None,
    k: int = 8,
    include_context: bool = False,
) -> dict[str, Any]:
    """Return note summaries."""
    return {
        "ok": True,
        "summaries": [
            {
                "note_id": "n-1",
                "summary": "Vendor B was chosen for the migration.",
                "updated_at": "2026-07-30T10:00:00Z",
            }
        ],
    }


@mcp.tool()
def delete_note(user_id: str, note_id: str) -> dict[str, Any]:
    """Delete a note."""
    return {"ok": True, "deleted": note_id, "user_id": user_id}


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
    """Update a note."""
    return {"ok": True, "note": {"note_id": note_id, "title": title or "unchanged"}}


@mcp.tool()
def move_note(user_id: str, note_id: str, folder_id: str) -> dict[str, Any]:
    """Move a note."""
    return {"ok": True, "note": {"note_id": note_id, "folder_id": folder_id}}


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
    """Create a note."""
    return {"ok": True, "note": {"note_id": "n-new", "title": title, "folder_id": folder_id}}


if __name__ == "__main__":
    mcp.settings.port = 8200
    mcp.run(transport="streamable-http")
