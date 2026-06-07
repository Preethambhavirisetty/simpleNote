"""
Tests for TagService unit tests and /api/tags/* endpoints.
"""
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.exceptions.base import AppException
from app.schema.base import ErrorCode
from app.schema.tag import TagCreate, TagUpdate
from tests.conftest import make_tag

# ── TagService unit tests ─────────────────────────────────────────────────────

@pytest.fixture
def tag_service():
    from app.services.tags import TagService

    svc = TagService()
    svc.repo = MagicMock()
    return svc


class TestTagServiceCreate:
    def test_create_success(self, tag_service, mock_db, current_user):
        tag_service.repo.get_by_name.return_value = None
        new_tag = make_tag(user_id=current_user.id, name="python")
        tag_service.repo.create.return_value = new_tag

        result = tag_service.create(mock_db, current_user.id, TagCreate(name="python"))

        assert result.name == "python"
        tag_service.repo.create.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_create_duplicate_raises_409(self, tag_service, mock_db, current_user):
        tag_service.repo.get_by_name.return_value = make_tag(name="python")

        with pytest.raises(AppException) as exc:
            tag_service.create(mock_db, current_user.id, TagCreate(name="python"))

        assert exc.value.status_code == 409
        assert exc.value.error_code == ErrorCode.DUPLICATE_ENTRY


class TestTagServiceGet:
    def test_get_existing_tag(self, tag_service, mock_db, current_user):
        tag = make_tag(user_id=current_user.id)
        tag_service.repo.get_by_id.return_value = tag

        result = tag_service.get(mock_db, tag.id, current_user.id)
        assert result.id == tag.id

    def test_get_nonexistent_raises_404(self, tag_service, mock_db, current_user):
        tag_service.repo.get_by_id.return_value = None

        with pytest.raises(AppException) as exc:
            tag_service.get(mock_db, uuid4(), current_user.id)

        assert exc.value.status_code == 404
        assert exc.value.error_code == ErrorCode.NOT_FOUND

    def test_cannot_access_other_users_tag(self, tag_service, mock_db):
        """Tag belonging to another user returns None from repo → 404."""
        tag_service.repo.get_by_id.return_value = None

        with pytest.raises(AppException) as exc:
            tag_service.get(mock_db, uuid4(), uuid4())

        assert exc.value.status_code == 404


class TestTagServiceUpdate:
    def test_update_to_new_name_success(self, tag_service, mock_db, current_user):
        tag = make_tag(user_id=current_user.id, name="old")
        tag_service.repo.get_by_id.return_value = tag
        tag_service.repo.get_by_name.return_value = None

        tag_service.update(mock_db, tag.id, current_user.id, TagUpdate(name="new"))

        tag_service.repo.update.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_update_same_name_is_allowed(self, tag_service, mock_db, current_user):
        """Updating to the exact same name should not raise a duplicate error."""
        tag = make_tag(user_id=current_user.id, name="python")
        tag_service.repo.get_by_id.return_value = tag

        # When name matches tag.name, get_by_name should NOT be called
        tag_service.update(mock_db, tag.id, current_user.id, TagUpdate(name="python"))

        tag_service.repo.get_by_name.assert_not_called()

    def test_update_name_conflict_raises_409(self, tag_service, mock_db, current_user):
        tag = make_tag(user_id=current_user.id, name="old")
        tag_service.repo.get_by_id.return_value = tag
        tag_service.repo.get_by_name.return_value = make_tag(name="taken")

        with pytest.raises(AppException) as exc:
            tag_service.update(mock_db, tag.id, current_user.id, TagUpdate(name="taken"))

        assert exc.value.status_code == 409


class TestTagServiceDelete:
    def test_delete_success(self, tag_service, mock_db, current_user):
        tag = make_tag(user_id=current_user.id)
        tag_service.repo.get_by_id.return_value = tag

        tag_service.delete(mock_db, tag.id, current_user.id)

        tag_service.repo.delete.assert_called_once_with(mock_db, tag)
        mock_db.commit.assert_called_once()

    def test_delete_nonexistent_raises_404(self, tag_service, mock_db, current_user):
        tag_service.repo.get_by_id.return_value = None

        with pytest.raises(AppException) as exc:
            tag_service.delete(mock_db, uuid4(), current_user.id)

        assert exc.value.status_code == 404


# ── Tag endpoint tests ────────────────────────────────────────────────────────

class TestListTagsEndpoint:
    def test_requires_auth(self, unauthed_client):
        resp = unauthed_client.get("/api/tags/")
        assert resp.status_code == 401

    def test_returns_tags(self, client):
        from app.services.tags import TagService

        tags = [make_tag(), make_tag()]
        with patch.object(TagService, "list", return_value=tags):
            resp = client.get("/api/tags/")

        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 2

    def test_empty_list(self, client):
        from app.services.tags import TagService

        with patch.object(TagService, "list", return_value=[]):
            resp = client.get("/api/tags/")

        assert resp.status_code == 200
        assert resp.json()["data"] == []


class TestCreateTagEndpoint:
    def test_requires_auth(self, unauthed_client):
        resp = unauthed_client.post("/api/tags/", json={"name": "python"})
        assert resp.status_code == 401

    def test_success(self, client):
        from app.services.tags import TagService

        tag = make_tag(name="python")
        with patch.object(TagService, "create", return_value=tag):
            resp = client.post("/api/tags/", json={"name": "python"})

        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == "python"

    def test_duplicate_tag_returns_409(self, client):
        from app.services.tags import TagService

        with patch.object(
            TagService,
            "create",
            side_effect=AppException("Tag 'python' already exists", 409, ErrorCode.DUPLICATE_ENTRY),
        ):
            resp = client.post("/api/tags/", json={"name": "python"})

        assert resp.status_code == 409


class TestGetTagEndpoint:
    def test_success(self, client):
        from app.services.tags import TagService

        tag = make_tag()
        with patch.object(TagService, "get", return_value=tag):
            resp = client.get(f"/api/tags/{tag.id}")

        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == tag.name

    def test_not_found_returns_404(self, client):
        from app.services.tags import TagService

        with patch.object(
            TagService,
            "get",
            side_effect=AppException("Tag not found", 404, ErrorCode.NOT_FOUND),
        ):
            resp = client.get(f"/api/tags/{uuid4()}")

        assert resp.status_code == 404


class TestUpdateTagEndpoint:
    def test_success(self, client):
        from app.services.tags import TagService

        tag = make_tag(name="updated")
        with patch.object(TagService, "update", return_value=tag):
            resp = client.patch(f"/api/tags/{tag.id}", json={"name": "updated"})

        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == "updated"

    def test_requires_auth(self, unauthed_client):
        resp = unauthed_client.patch(f"/api/tags/{uuid4()}", json={"name": "x"})
        assert resp.status_code == 401

    def test_name_conflict_returns_409(self, client):
        from app.services.tags import TagService

        with patch.object(
            TagService,
            "update",
            side_effect=AppException("Tag 'taken' already exists", 409, ErrorCode.DUPLICATE_ENTRY),
        ):
            resp = client.patch(f"/api/tags/{uuid4()}", json={"name": "taken"})

        assert resp.status_code == 409


class TestDeleteTagEndpoint:
    def test_success(self, client):
        from app.services.tags import TagService

        with patch.object(TagService, "delete", return_value=None):
            resp = client.delete(f"/api/tags/{uuid4()}")

        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_requires_auth(self, unauthed_client):
        resp = unauthed_client.delete(f"/api/tags/{uuid4()}")
        assert resp.status_code == 401

    def test_not_found_returns_404(self, client):
        from app.services.tags import TagService

        with patch.object(
            TagService,
            "delete",
            side_effect=AppException("Tag not found", 404, ErrorCode.NOT_FOUND),
        ):
            resp = client.delete(f"/api/tags/{uuid4()}")

        assert resp.status_code == 404
