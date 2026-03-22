"""
Tests for NoteService unit tests and /api/notes/* endpoints.

Celery dispatch helpers (_dispatch_ingest, _dispatch_delete) are patched at the
module level in every test so no Redis connection is attempted.
"""
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.exceptions.base import AppException
from app.schema.base import ErrorCode
from app.schema.note import NoteCreate, NoteMoveRequest, NoteUpdate
from tests.conftest import make_note, make_tag

# Suppress all Celery send_task calls for the entire test module.
pytestmark = [
    pytest.mark.usefixtures("no_celery"),
]

_SIMPLE_DOC = {
    "type": "doc",
    "content": [
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "Hello world"}],
        }
    ],
}

_EMPTY_DOC = {"type": "doc", "content": []}


# ── NoteService unit tests ────────────────────────────────────────────────────

@pytest.fixture
def note_service():
    from app.services.notes import NoteService

    svc = NoteService()
    svc.repo = MagicMock()
    svc.tag_repo = MagicMock()
    svc.folder_repo = MagicMock()
    return svc


class TestNoteServiceCreate:
    def test_create_extracts_content_text(self, note_service, mock_db, current_user):
        folder_id = uuid4()
        created = make_note(user_id=current_user.id, folder_id=folder_id, title="T", content=_SIMPLE_DOC)
        note_service.repo.create.return_value = created

        payload = NoteCreate(title="T", folder_id=folder_id, content=_SIMPLE_DOC)
        result = note_service.create(mock_db, current_user.id, payload, current_user.role)

        # repo.create(db, user_id, data, content_text) → content_text is args[3]
        call_args = note_service.repo.create.call_args
        content_text_arg = call_args.args[3]
        assert content_text_arg == "Hello world"
        assert result.title == "T"

    def test_create_with_empty_doc_extracts_empty_text(self, note_service, mock_db, current_user):
        folder_id = uuid4()
        created = make_note(folder_id=folder_id, content=_EMPTY_DOC)
        note_service.repo.create.return_value = created

        payload = NoteCreate(title="Empty", folder_id=folder_id, content=_EMPTY_DOC)
        note_service.create(mock_db, current_user.id, payload, current_user.role)

        call_args = note_service.repo.create.call_args
        content_text_arg = call_args.args[3]
        assert content_text_arg == ""


class TestNoteServiceGet:
    def test_get_existing_note(self, note_service, mock_db, current_user):
        note = make_note(user_id=current_user.id)
        note_service.repo.get_by_id.return_value = note

        result = note_service.get(mock_db, note.id, current_user.id)
        assert result.id == note.id

    def test_get_nonexistent_raises_404(self, note_service, mock_db, current_user):
        note_service.repo.get_by_id.return_value = None

        with pytest.raises(AppException) as exc:
            note_service.get(mock_db, uuid4(), current_user.id)

        assert exc.value.status_code == 404
        assert exc.value.error_code == ErrorCode.NOT_FOUND

    def test_cannot_access_other_users_note(self, note_service, mock_db):
        """Repo returns None for cross-user access → 404."""
        note_service.repo.get_by_id.return_value = None

        with pytest.raises(AppException) as exc:
            note_service.get(mock_db, uuid4(), uuid4())

        assert exc.value.status_code == 404


class TestNoteServiceUpdate:
    def test_update_with_content_re_extracts_text(self, note_service, mock_db, current_user):
        note = make_note(user_id=current_user.id)
        note_service.repo.get_by_id.return_value = note

        payload = NoteUpdate(content=_SIMPLE_DOC)
        note_service.update(mock_db, note.id, current_user.id, payload, current_user.role)

        # repo.update(db, note, payload, content_text) → content_text is args[3]
        update_call = note_service.repo.update.call_args
        content_text_arg = update_call.args[3]
        assert content_text_arg == "Hello world"

    def test_update_without_content_passes_none_text(self, note_service, mock_db, current_user):
        note = make_note(user_id=current_user.id)
        note_service.repo.get_by_id.return_value = note

        payload = NoteUpdate(title="New Title")
        note_service.update(mock_db, note.id, current_user.id, payload, current_user.role)

        update_call = note_service.repo.update.call_args
        content_text_arg = update_call.args[3]
        assert content_text_arg is None


class TestNoteServiceMove:
    def test_move_to_different_folder(self, note_service, mock_db, current_user):
        note = make_note(user_id=current_user.id)
        note_service.repo.get_by_id.return_value = note
        new_folder_id = uuid4()

        note_service.move(mock_db, note.id, current_user.id, NoteMoveRequest(folder_id=new_folder_id))

        assert note.folder_id == new_folder_id
        mock_db.commit.assert_called_once()


class TestNoteServiceTagOperations:
    def test_add_tag_success(self, note_service, mock_db, current_user):
        note = make_note(user_id=current_user.id)
        tag = make_tag(user_id=current_user.id)
        note_service.repo.get_by_id.return_value = note
        note_service.tag_repo.get_by_id.return_value = tag
        note_service.repo.has_tag.return_value = False

        note_service.add_tag(mock_db, note.id, tag.id, current_user.id)

        note_service.repo.add_tag.assert_called_once_with(mock_db, note.id, tag.id)
        mock_db.commit.assert_called_once()

    def test_add_nonexistent_tag_raises_404(self, note_service, mock_db, current_user):
        note = make_note(user_id=current_user.id)
        note_service.repo.get_by_id.return_value = note
        note_service.tag_repo.get_by_id.return_value = None

        with pytest.raises(AppException) as exc:
            note_service.add_tag(mock_db, note.id, uuid4(), current_user.id)

        assert exc.value.status_code == 404

    def test_add_duplicate_tag_raises_409(self, note_service, mock_db, current_user):
        note = make_note(user_id=current_user.id)
        tag = make_tag(user_id=current_user.id)
        note_service.repo.get_by_id.return_value = note
        note_service.tag_repo.get_by_id.return_value = tag
        note_service.repo.has_tag.return_value = True

        with pytest.raises(AppException) as exc:
            note_service.add_tag(mock_db, note.id, tag.id, current_user.id)

        assert exc.value.status_code == 409
        assert exc.value.error_code == ErrorCode.DUPLICATE_ENTRY

    def test_remove_tag_success(self, note_service, mock_db, current_user):
        note = make_note(user_id=current_user.id)
        tag = make_tag(user_id=current_user.id)
        note_service.repo.get_by_id.return_value = note
        note_service.repo.has_tag.return_value = True

        note_service.remove_tag(mock_db, note.id, tag.id, current_user.id)

        note_service.repo.remove_tag.assert_called_once_with(mock_db, note.id, tag.id)
        mock_db.commit.assert_called_once()

    def test_remove_tag_not_on_note_raises_404(self, note_service, mock_db, current_user):
        note = make_note(user_id=current_user.id)
        note_service.repo.get_by_id.return_value = note
        note_service.repo.has_tag.return_value = False

        with pytest.raises(AppException) as exc:
            note_service.remove_tag(mock_db, note.id, uuid4(), current_user.id)

        assert exc.value.status_code == 404


class TestNoteServiceDelete:
    def test_delete_success(self, note_service, mock_db, current_user):
        note = make_note(user_id=current_user.id)
        note_service.repo.get_by_id.return_value = note

        note_service.delete(mock_db, note.id, current_user.id, current_user.role)

        note_service.repo.delete.assert_called_once_with(mock_db, note)
        mock_db.commit.assert_called_once()

    def test_delete_nonexistent_raises_404(self, note_service, mock_db, current_user):
        note_service.repo.get_by_id.return_value = None

        with pytest.raises(AppException) as exc:
            note_service.delete(mock_db, uuid4(), current_user.id, current_user.role)

        assert exc.value.status_code == 404


# ── Note endpoint tests ───────────────────────────────────────────────────────

class TestListNotesEndpoint:
    def test_requires_auth(self, unauthed_client):
        resp = unauthed_client.get("/api/notes/")
        assert resp.status_code == 401

    def test_returns_list(self, client):
        from app.services.notes import NoteService

        notes = [make_note(), make_note()]
        with patch.object(NoteService, "list", return_value=notes):
            resp = client.get("/api/notes/")

        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 2

    def test_pinned_only_query_param_accepted(self, client):
        from app.services.notes import NoteService

        with patch.object(NoteService, "list", return_value=[]) as mock_list:
            client.get("/api/notes/?pinned_only=true")

        _, kwargs = mock_list.call_args
        assert kwargs.get("pinned_only") is True

    def test_search_query_param_forwarded(self, client):
        from app.services.notes import NoteService

        with patch.object(NoteService, "list", return_value=[]) as mock_list:
            client.get("/api/notes/?search=hello")

        _, kwargs = mock_list.call_args
        assert kwargs.get("search") == "hello"

    def test_limit_out_of_range_returns_422(self, client):
        resp = client.get("/api/notes/?limit=0")
        assert resp.status_code == 422

    def test_limit_max_exceeded_returns_422(self, client):
        resp = client.get("/api/notes/?limit=201")
        assert resp.status_code == 422


class TestCreateNoteEndpoint:
    def test_requires_auth(self, unauthed_client):
        folder_id = str(uuid4())
        resp = unauthed_client.post("/api/notes/", json={"title": "T", "folder_id": folder_id, "content": _SIMPLE_DOC})
        assert resp.status_code == 401

    def test_success(self, client):
        from app.services.notes import NoteService

        folder_id = uuid4()
        note = make_note(folder_id=folder_id, title="T", content=_SIMPLE_DOC, content_text="Hello world")
        with patch.object(NoteService, "create", return_value=note):
            resp = client.post("/api/notes/", json={"title": "T", "folder_id": str(folder_id), "content": _SIMPLE_DOC})

        assert resp.status_code == 200
        assert resp.json()["data"]["title"] == "T"

    def test_missing_title_returns_422(self, client):
        resp = client.post("/api/notes/", json={"folder_id": str(uuid4()), "content": _SIMPLE_DOC})
        assert resp.status_code == 422

    def test_missing_folder_id_returns_422(self, client):
        """folder_id is now required — omitting it must return 422."""
        resp = client.post("/api/notes/", json={"title": "T", "content": _SIMPLE_DOC})
        assert resp.status_code == 422

    def test_content_defaults_to_empty_dict(self, client):
        """Omitting content is valid – it defaults to an empty dict."""
        from app.services.notes import NoteService

        folder_id = uuid4()
        note = make_note(folder_id=folder_id, title="T", content={}, content_text="")
        with patch.object(NoteService, "create", return_value=note):
            resp = client.post("/api/notes/", json={"title": "T", "folder_id": str(folder_id)})

        assert resp.status_code == 200


class TestGetNoteEndpoint:
    def test_requires_auth(self, unauthed_client):
        resp = unauthed_client.get(f"/api/notes/{uuid4()}")
        assert resp.status_code == 401

    def test_success(self, client):
        from app.services.notes import NoteService

        note = make_note()
        with patch.object(NoteService, "get", return_value=note):
            resp = client.get(f"/api/notes/{note.id}")

        assert resp.status_code == 200

    def test_not_found_returns_404(self, client):
        from app.services.notes import NoteService

        with patch.object(
            NoteService,
            "get",
            side_effect=AppException("Note not found", 404, ErrorCode.NOT_FOUND),
        ):
            resp = client.get(f"/api/notes/{uuid4()}")

        assert resp.status_code == 404


class TestUpdateNoteEndpoint:
    def test_success(self, client):
        from app.services.notes import NoteService

        note = make_note(title="Updated")
        with patch.object(NoteService, "update", return_value=note):
            resp = client.patch(f"/api/notes/{note.id}", json={"title": "Updated"})

        assert resp.status_code == 200
        assert resp.json()["data"]["title"] == "Updated"

    def test_requires_auth(self, unauthed_client):
        resp = unauthed_client.patch(f"/api/notes/{uuid4()}", json={"title": "X"})
        assert resp.status_code == 401


class TestMoveNoteEndpoint:
    def test_move_to_folder(self, client):
        from app.services.notes import NoteService

        folder_id = uuid4()
        note = make_note(folder_id=folder_id)
        with patch.object(NoteService, "move", return_value=note):
            resp = client.patch(
                f"/api/notes/{note.id}/move",
                json={"folder_id": str(folder_id)},
            )

        assert resp.status_code == 200
        assert resp.json()["data"]["folder_id"] == str(folder_id)

    def test_move_missing_folder_id_returns_422(self, client):
        """folder_id is required in NoteMoveRequest."""
        resp = client.patch(
            f"/api/notes/{uuid4()}/move",
            json={"folder_id": None},
        )
        assert resp.status_code == 422


class TestDeleteNoteEndpoint:
    def test_success(self, client):
        from app.services.notes import NoteService

        with patch.object(NoteService, "delete", return_value=None):
            resp = client.delete(f"/api/notes/{uuid4()}")

        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestNoteTagEndpoints:
    def test_add_tag_success(self, client):
        from app.services.notes import NoteService

        note_id, tag_id = uuid4(), uuid4()
        with patch.object(NoteService, "add_tag", return_value=None):
            resp = client.post(f"/api/notes/{note_id}/tags/{tag_id}")

        assert resp.status_code == 200

    def test_add_tag_not_found_returns_404(self, client):
        from app.services.notes import NoteService

        with patch.object(
            NoteService,
            "add_tag",
            side_effect=AppException("Tag not found", 404, ErrorCode.NOT_FOUND),
        ):
            resp = client.post(f"/api/notes/{uuid4()}/tags/{uuid4()}")

        assert resp.status_code == 404

    def test_add_duplicate_tag_returns_409(self, client):
        from app.services.notes import NoteService

        with patch.object(
            NoteService,
            "add_tag",
            side_effect=AppException("Tag already added", 409, ErrorCode.DUPLICATE_ENTRY),
        ):
            resp = client.post(f"/api/notes/{uuid4()}/tags/{uuid4()}")

        assert resp.status_code == 409

    def test_remove_tag_success(self, client):
        from app.services.notes import NoteService

        with patch.object(NoteService, "remove_tag", return_value=None):
            resp = client.delete(f"/api/notes/{uuid4()}/tags/{uuid4()}")

        assert resp.status_code == 200

    def test_remove_tag_not_on_note_returns_404(self, client):
        from app.services.notes import NoteService

        with patch.object(
            NoteService,
            "remove_tag",
            side_effect=AppException("Tag not found on note", 404, ErrorCode.NOT_FOUND),
        ):
            resp = client.delete(f"/api/notes/{uuid4()}/tags/{uuid4()}")

        assert resp.status_code == 404

    def test_requires_auth_add_tag(self, unauthed_client):
        resp = unauthed_client.post(f"/api/notes/{uuid4()}/tags/{uuid4()}")
        assert resp.status_code == 401

    def test_requires_auth_remove_tag(self, unauthed_client):
        resp = unauthed_client.delete(f"/api/notes/{uuid4()}/tags/{uuid4()}")
        assert resp.status_code == 401
