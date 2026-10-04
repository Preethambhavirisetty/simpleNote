"""
Utilities for working with TipTap JSON documents.

TipTap serialises editor content as a recursive node tree:
{
  "type": "doc",
  "content": [
    {
      "type": "paragraph",
      "content": [
        {"type": "text", "text": "Hello world"}
      ]
    }
  ]
}

Leaf nodes with type "text" carry the actual string content.
Block-level nodes (paragraph, heading, listItem, blockquote, …) act as
containers whose children eventually resolve to text leaves.
"""

# Block-level node types that should be separated by a newline in the
# derived plain-text output rather than a space.
_BLOCK_TYPES = {
    "paragraph",
    "heading",
    "blockquote",
    "listItem",
    "codeBlock",
    "horizontalRule",
    "tableRow",
    "tableCell",
    "tableHeader",
}

MAX_DOCUMENT_DEPTH = 100


def extract_text(doc: dict) -> str:
    """
    Walk a TipTap JSON document and return derived plain text.

    Block-level nodes are separated by newlines; inline text nodes are
    concatenated directly (TipTap already includes any spacing in the
    text value itself).

    Returns an empty string for None or non-dict input.
    """
    if not doc or not isinstance(doc, dict):
        return ""

    parts: list[str] = []

    def _walk(node: dict, depth: int) -> None:
        if depth > MAX_DOCUMENT_DEPTH:
            raise ValueError(f"TipTap document exceeds maximum depth of {MAX_DOCUMENT_DEPTH}")

        node_type = node.get("type", "")

        if node_type == "text":
            text = node.get("text", "")
            if text:
                parts.append(text)
            return

        if node_type == "hardBreak":
            parts.append("\n")
            return

        children = node.get("content", [])

        if node_type in _BLOCK_TYPES and parts and parts[-1] != "\n":
            parts.append("\n")

        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict):
                    _walk(child, depth + 1)

        if node_type in _BLOCK_TYPES and parts and parts[-1] != "\n":
            parts.append("\n")

    _walk(doc, 1)
    return "".join(parts).strip()
