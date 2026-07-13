from app.agent_workflow.evidence_grade import filter_conflict_gaps
from app.agent_workflow.query_filter_conflicts import (
    extract_lab_from_query,
    extract_site_from_query,
    query_filter_conflict_gaps,
)


def test_extract_site_and_lab_from_query():
    query = "can we host a server at BGL site in lab RTP12-F340?"
    assert extract_site_from_query(query) == "BGL"
    assert extract_lab_from_query(query) == "RTP12-F340"


def test_query_filter_conflict_bgl_rtp_lab():
    gaps = query_filter_conflict_gaps(
        "do we have enough power at BGL site in lab RTP12-F340?"
    )
    assert gaps
    assert "BGL" in gaps[0]
    assert "RTP12-F340" in gaps[0]


def test_filter_conflict_gaps_include_query_without_artifacts():
    gaps = filter_conflict_gaps(
        [],
        user_query="do we have enough power at BGL site in lab RTP12-F340?",
    )
    assert gaps
