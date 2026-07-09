from app.agent_workflow.nodes.synthesizer import _fallback_from_facts


def test_fallback_from_facts_uses_markdown_heading():
    text = _fallback_from_facts([{"text": "Dashboard count: 12"}, {"text": "Panels: 4"}])
    assert text.startswith("## Results")
    assert "\n- Dashboard count: 12" in text


def test_formatting_gaps_flags_wall_of_text():
    from app.agent_workflow.nodes.reviewer import _formatting_gaps

    wall = "word " * 80
    assert _formatting_gaps(wall)
    assert "GFM markdown" in _formatting_gaps(wall)[0]


def test_formatting_gaps_accepts_structured_markdown():
    from app.agent_workflow.nodes.reviewer import _formatting_gaps

    structured = "## Summary\n\n- item one\n- item two\n\nMore detail " + ("x" * 200)
    assert _formatting_gaps(structured) == []
