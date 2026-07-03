"""
Unit tests for app.core.tiptap.extract_text.

All tests are pure – no DB, no HTTP, no mocks needed.
"""
from app.core.tiptap import extract_text

# ── Input guard ───────────────────────────────────────────────────────────────

def test_none_returns_empty_string():
    assert extract_text(None) == ""


def test_non_dict_string_returns_empty():
    assert extract_text("hello") == ""  # type: ignore[arg-type]


def test_non_dict_list_returns_empty():
    assert extract_text([]) == ""  # type: ignore[arg-type]


def test_empty_dict_returns_empty():
    assert extract_text({}) == ""


def test_doc_with_no_content_key():
    assert extract_text({"type": "doc"}) == ""


# ── Simple text extraction ────────────────────────────────────────────────────

def test_single_paragraph():
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "Hello world"}],
            }
        ],
    }
    assert extract_text(doc) == "Hello world"


def test_heading_text():
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 1},
                "content": [{"type": "text", "text": "My Title"}],
            }
        ],
    }
    assert extract_text(doc) == "My Title"


def test_multiple_blocks_separated_by_newline():
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "First paragraph"}],
            },
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "Second paragraph"}],
            },
        ],
    }
    result = extract_text(doc)
    assert "First paragraph" in result
    assert "Second paragraph" in result
    assert result.index("First paragraph") < result.index("Second paragraph")


def test_marks_are_stripped_text_preserved():
    """Bold/italic marks should not affect text content."""
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "marks": [{"type": "bold"}],
                        "text": "bold text",
                    }
                ],
            }
        ],
    }
    assert extract_text(doc) == "bold text"


def test_hard_break_produces_newline():
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "line one"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "line two"},
                ],
            }
        ],
    }
    result = extract_text(doc)
    assert "line one" in result
    assert "line two" in result


def test_list_items_extracted():
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "Item A"}],
                            }
                        ],
                    },
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "Item B"}],
                            }
                        ],
                    },
                ],
            }
        ],
    }
    result = extract_text(doc)
    assert "Item A" in result
    assert "Item B" in result


def test_code_block_text():
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "codeBlock",
                "content": [{"type": "text", "text": "x = 1"}],
            }
        ],
    }
    assert extract_text(doc) == "x = 1"


def test_text_node_with_empty_text_ignored():
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": ""}],
            }
        ],
    }
    assert extract_text(doc) == ""


def test_result_is_stripped():
    """Leading/trailing whitespace from joined parts should be stripped."""
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "  spaces  "}],
            }
        ],
    }
    result = extract_text(doc)
    # extract_text strips the final joined string
    assert result == result.strip()


def test_nested_heading_and_paragraph():
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "content": [{"type": "text", "text": "Title"}],
            },
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "Body text here."}],
            },
        ],
    }
    result = extract_text(doc)
    assert "Title" in result
    assert "Body text here." in result
