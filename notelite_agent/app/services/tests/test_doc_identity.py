"""Document identity must be stable across folder moves.

The doc id is user + note only; folder_id is mutable metadata. If folder_id ever
leaks back into the id, moving a note forks a new document and orphans the old
folder's vectors (duplicate retrieval results, unbounded index growth).
"""
from types import SimpleNamespace

import pytest

from app.services.ingestion.actions.services import IngestionActionServices
from app.services.ingestion.orchestrator import IngestionOrchestrator


class FakeVectorStore:
    def __init__(self):
        self.deleted = []

    def delete_document(self, doc_id):
        self.deleted.append(doc_id)


class FakePostgresStore:
    def __init__(self):
        self.deleted = []

    def delete_document(self, doc_id):
        self.deleted.append(doc_id)


def orchestrator_with_fakes():
    orchestrator = IngestionOrchestrator.__new__(IngestionOrchestrator)
    orchestrator._vector_store = FakeVectorStore()
    orchestrator.postgres_store = FakePostgresStore()
    return orchestrator


def payload(folder_id="folder-a", **overrides):
    data = {"user_id": "user-1", "folder_id": folder_id, "note_id": "note-1"}
    data.update(overrides)
    return data


def test_doc_id_excludes_folder():
    assert IngestionOrchestrator._doc_id(payload()) == "user-1-note-1"


def test_doc_id_is_stable_across_folder_moves():
    before_move = IngestionOrchestrator._doc_id(payload(folder_id="folder-a"))
    after_move = IngestionOrchestrator._doc_id(payload(folder_id="folder-b"))
    assert before_move == after_move


def test_doc_id_still_requires_all_payload_fields():
    for missing in ("user_id", "folder_id", "note_id"):
        with pytest.raises(ValueError, match=missing):
            IngestionOrchestrator._doc_id(payload(**{missing: None}))


def test_delete_after_move_targets_the_same_document():
    """A note ingested in folder A then deleted from folder B removes one doc."""
    orchestrator = orchestrator_with_fakes()
    ingested_doc_id = IngestionOrchestrator._doc_id(payload(folder_id="folder-a"))

    # Payload omits `version`, so the stale-delete guard skips its DB check.
    result = orchestrator.delete_action(payload(folder_id="folder-b"))

    assert result["status"] == "deleted"
    assert orchestrator._vector_store.deleted == [ingested_doc_id]
    assert orchestrator.postgres_store.deleted == [ingested_doc_id]


def test_actions_doc_id_matches_orchestrator_doc_id():
    """The debug actions path must inspect the same doc the live pipeline writes."""
    action_payload = SimpleNamespace(user_id="user-1", folder_id="folder-a", note_id="note-1")
    assert IngestionActionServices._doc_id(action_payload) == IngestionOrchestrator._doc_id(payload())
