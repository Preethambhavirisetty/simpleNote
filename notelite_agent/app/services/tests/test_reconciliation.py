"""Reconciliation task: payload contracts and enqueue behavior."""
from unittest.mock import MagicMock, patch

from app.services.ingestion.workers import reconciliation


def stale_note_row():
    return {
        "note_id": "n1",
        "user_id": "u1",
        "folder_id": "f1",
        "note_title": "Title",
        "description": "",
        "text": "hello world",
        "version": 3,
        "folder_title": "Work",
        "tags": ["a", "b"],
    }


def orphan_row():
    return {"doc_id": "u1-n2", "user_id": "u1", "folder_id": "f1", "note_id": "n2"}


def test_upsert_payload_matches_the_ingestion_contract():
    payload = reconciliation.upsert_payload(stale_note_row(), trace_id="t1")

    assert payload["action"] == "upsert"
    assert payload["version"] == 3          # version guard input
    assert payload["trace_id"] == "t1"
    assert payload["tags"] == ["a", "b"]
    for key in ("user_id", "folder_id", "note_id", "tenant_id", "folder_title",
                "note_title", "description", "text", "role"):
        assert key in payload


def test_delete_payload_omits_version_so_the_delete_proceeds():
    """The stale-delete guard only runs when `version` is present; a repair
    delete targets a note that is gone/emptied and must go through."""
    payload = reconciliation.delete_payload(orphan_row(), trace_id="t1")

    assert payload["action"] == "delete"
    assert "version" not in payload
    assert payload["note_id"] == "n2"


def test_reconcile_enqueues_repairs_for_both_drift_directions():
    with patch.object(reconciliation, "DatabaseManager"), \
         patch.object(reconciliation, "find_stale_notes", return_value=[stale_note_row()]), \
         patch.object(reconciliation, "find_orphan_documents", return_value=[orphan_row()]), \
         patch.object(reconciliation, "ingest_in_background") as ingest:
        result = reconciliation.reconcile_index(limit=10)

    assert result == {"reingest_enqueued": 1, "delete_enqueued": 1}
    actions = [call.args[0]["action"] for call in ingest.delay.call_args_list]
    assert actions == ["upsert", "delete"]
    # One trace id ties the whole sweep together.
    trace_ids = {call.args[0]["trace_id"] for call in ingest.delay.call_args_list}
    assert len(trace_ids) == 1


def test_reconcile_with_no_drift_enqueues_nothing():
    with patch.object(reconciliation, "DatabaseManager"), \
         patch.object(reconciliation, "find_stale_notes", return_value=[]), \
         patch.object(reconciliation, "find_orphan_documents", return_value=[]), \
         patch.object(reconciliation, "ingest_in_background") as ingest:
        result = reconciliation.reconcile_index()

    assert result == {"reingest_enqueued": 0, "delete_enqueued": 0}
    ingest.delay.assert_not_called()
