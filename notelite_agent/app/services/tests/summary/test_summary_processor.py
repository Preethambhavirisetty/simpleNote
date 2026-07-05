from app.services.ingestion.processors.summary.summary_processor import SummaryProcessor
from app.services.ingestion.processors.summary.summary_helpers import repair_summary_format


def test_direct_summary_repairs_useful_list_output(monkeypatch):
    monkeypatch.setattr(
        "app.services.ingestion.processors.summary.summary_processor.llm_call_general",
        lambda *args, **kwargs: "- Deployment v2.1.0 completed successfully\n- Qdrant p99 search improved after HNSW tuning",
    )

    result = SummaryProcessor().process([
        "The v2.1.0 release went out without issues.",
        "Qdrant p99 search improved after HNSW tuning.",
    ])

    assert result.summary == (
        "Deployment v2.1.0 completed successfully "
        "Qdrant p99 search improved after HNSW tuning."
    )
    assert "summary fallback: direct format repaired" in result.events
    assert "summary completed: direct" in result.events


def test_direct_summary_still_rejects_useless_output(monkeypatch):
    monkeypatch.setattr(
        "app.services.ingestion.processors.summary.summary_processor.llm_call_general",
        lambda *args, **kwargs: "I cannot summarize without the text provided.",
    )

    result = SummaryProcessor().process(["The platform team reviewed deployment and Qdrant performance."])

    assert result.summary == ""
    assert "summary discarded: low quality" in result.events


def test_summary_format_repair_drops_incomplete_trailing_clause():
    assert repair_summary_format(
        "The release completed successfully. The team assigned follow-up work, and draft"
    ) == "The release completed successfully."
