from app.agent_workflow.evidence_grade import (
    claim_class_from_query,
    draft_claim_consistency_gaps,
    question_requires_row_evidence,
    row_evidence_gaps,
)
from app.agent_workflow.playbooks.router import resolve_playbook_plan


def test_claim_class_discovery():
    assert claim_class_from_query("what dashboards do we have for lab row power?") == "discovery"


def test_claim_class_listing():
    assert claim_class_from_query("which rows in RTP have more than 30 kW available power?") == "listing"


def test_claim_class_existence():
    assert claim_class_from_query("can we host a new server in RTP12-F340 — is there enough power?") == "existence"


def test_row_evidence_gap_without_rows():
    gaps = row_evidence_gaps(
        "which rows in RTP have more than 30 kW available power?",
        [{"tool": "get_dashboard_tokens", "raw_ref": {"items": []}}],
    )
    assert gaps


def test_row_evidence_gap_with_unusable_rows():
    gaps = row_evidence_gaps(
        "is there at least 30 kW available in RTP?",
        [{"tool": "get_panel_data", "raw_ref": {"ok": True, "rows": [{"ROW": "AA", "Available Power": "NA"}], "rows_usable": False}}],
    )
    assert any("usable" in gap.lower() for gap in gaps)


def test_playbook_matches_capacity_question():
    plan = resolve_playbook_plan("can you check if i have available power of atleast 30kv to host a new server in rtp region?")
    assert plan is not None
    assert plan.get("playbook_id") == "row_power_capacity"
    assert "enough available power" in str(plan.get("goal") or "").lower()
    assert plan.get("evidence_required") == "row_level"
    assert any(step.get("require_row_level") for step in plan.get("steps") or [])


def test_playbook_matches_listing_question():
    plan = resolve_playbook_plan("which rows in the RTP region have more than 30 kW available power right now?")
    assert plan is not None
    assert plan.get("playbook_id") == "row_power_listing"


def test_playbook_matches_discovery_question():
    plan = resolve_playbook_plan("what dashboards do we have for checking lab row power availability?")
    assert plan is not None
    assert plan.get("playbook_id") == "dashboard_discovery"


def test_discovery_answer_gap_when_dashboard_missing_from_draft():
    from app.agent_workflow.evidence_grade import discovery_answer_gaps

    gaps = discovery_answer_gaps(
        "what dashboards do we have for checking lab row power availability?",
        "Here are some dashboards related to power.",
        [{"tool": "list_dashboards", "raw_ref": {"items": [{"name": "autopod_rows_availability"}]}}],
    )
    assert gaps
    assert "autopod_rows_availability" in gaps[0]


def test_draft_claim_consistency_flags_na_yes():
    gaps = draft_claim_consistency_gaps(
        "is there enough power in RTP10-330?",
        "Yes, there is sufficient power. | Row | Available Power |\n| AA | NA |",
        [{"tool": "get_panel_data", "raw_ref": {"ok": True, "rows": [{"ROW": "AA", "Available Power": "NA"}], "rows_usable": False}}],
    )
    assert gaps
