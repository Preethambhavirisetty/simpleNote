"""
Tests for FolderService unit tests and /api/folders/* endpoints.
"""
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.exceptions.base import AppException
from app.schema.base import ErrorCode
from app.schema.folder import FolderCreate, FolderUpdate
from tests.conftest import make_folder

# ── FolderService unit tests ──────────────────────────────────────────────────

@pytest.fixture
def folder_service():
    from app.services.folders import FolderService

    svc = FolderService()
    svc.repo = MagicMock()
    return svc


class TestFolderServiceCreate:
    def test_create_success(self, folder_service, mock_db, current_user):
        folder_service.repo.get_by_name.return_value = None
        new_folder = make_folder(user_id=current_user.id, name="Work")
        folder_service.repo.create.return_value = new_folder

        result = folder_service.create(mock_db, current_user.id, FolderCreate(name="Work"))

        assert result.name == "Work"
        folder_service.repo.create.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_create_duplicate_name_raises_409(self, folder_service, mock_db, current_user):
        folder_service.repo.get_by_name.return_value = make_folder(name="Work")

        with pytest.raises(AppException) as exc:
            folder_service.create(mock_db, current_user.id, FolderCreate(name="Work"))

        assert exc.value.status_code == 409
        assert exc.value.error_code == ErrorCode.DUPLICATE_ENTRY


class TestFolderServiceGet:
    def test_get_existing_folder(self, folder_service, mock_db, current_user):
        folder = make_folder(user_id=current_user.id)
        folder_service.repo.get_by_id.return_value = folder

        result = folder_service.get(mock_db, folder.id, current_user.id)
        assert result.id == folder.id

    def test_get_nonexistent_raises_404(self, folder_service, mock_db, current_user):
        folder_service.repo.get_by_id.return_value = None

        with pytest.raises(AppException) as exc:
            folder_service.get(mock_db, uuid4(), current_user.id)

        assert exc.value.status_code == 404
        assert exc.value.error_code == ErrorCode.NOT_FOUND

    def test_cannot_access_other_users_folder(self, folder_service, mock_db):
        """Folder that belongs to a different user returns None from repo → 404."""
        folder_service.repo.get_by_id.return_value = None

        with pytest.raises(AppException) as exc:
            folder_service.get(mock_db, uuid4(), uuid4())

        assert exc.value.status_code == 404


class TestFolderServiceUpdate:
    def test_update_success(self, folder_service, mock_db, current_user):
        folder = make_folder(user_id=current_user.id, name="Old")
        folder_service.repo.get_by_id.return_value = folder
        folder_service.repo.get_by_name.return_value = None

        folder_service.update(mock_db, folder.id, current_user.id, FolderUpdate(name="New"))

        folder_service.repo.update.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_update_same_name_is_allowed(self, folder_service, mock_db, current_user):
        """Renaming to the same name should not trigger duplicate check."""
        folder = make_folder(user_id=current_user.id, name="Work")
        folder_service.repo.get_by_id.return_value = folder

        # Should NOT raise even though the name is the same
        folder_service.update(mock_db, folder.id, current_user.id, FolderUpdate(name="Work"))

        # get_by_name should NOT be called when name is unchanged
        folder_service.repo.get_by_name.assert_not_called()

    def test_update_name_conflict_raises_409(self, folder_service, mock_db, current_user):
        folder = make_folder(user_id=current_user.id, name="Old")
        folder_service.repo.get_by_id.return_value = folder
        folder_service.repo.get_by_name.return_value = make_folder(name="Taken")

        with pytest.raises(AppException) as exc:
            folder_service.update(mock_db, folder.id, current_user.id, FolderUpdate(name="Taken"))

        assert exc.value.status_code == 409


class TestFolderServiceDelete:
    def test_delete_success(self, folder_service, mock_db, current_user):
        folder = make_folder(user_id=current_user.id)
        folder_service.repo.get_by_id.return_value = folder

        folder_service.delete(mock_db, folder.id, current_user.id)

        folder_service.repo.delete.assert_called_once_with(mock_db, folder)
        mock_db.commit.assert_called_once()

    def test_delete_nonexistent_raises_404(self, folder_service, mock_db, current_user):
        folder_service.repo.get_by_id.return_value = None

        with pytest.raises(AppException) as exc:
            folder_service.delete(mock_db, uuid4(), current_user.id)

        assert exc.value.status_code == 404


# ── Folder endpoint tests ─────────────────────────────────────────────────────

class TestListFoldersEndpoint:
    def test_requires_auth(self, unauthed_client):
        resp = unauthed_client.get("/api/folders/")
        assert resp.status_code == 401

    def test_returns_user_folders(self, client):
        from app.services.folders import FolderService

        folders = [make_folder(), make_folder()]
        with patch.object(FolderService, "list", return_value=folders):
            resp = client.get("/api/folders/")

        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 2

    def test_empty_list(self, client):
        from app.services.folders import FolderService

        with patch.object(FolderService, "list", return_value=[]):
            resp = client.get("/api/folders/")

        assert resp.status_code == 200
        assert resp.json()["data"] == []


class TestCreateFolderEndpoint:
    def test_requires_auth(self, unauthed_client):
        resp = unauthed_client.post("/api/folders/", json={"name": "Work"})
        assert resp.status_code == 401

    def test_success(self, client):
        from app.services.folders import FolderService

        new_folder = make_folder(name="Work")
        with patch.object(FolderService, "create", return_value=new_folder):
            resp = client.post("/api/folders/", json={"name": "Work"})

        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == "Work"

    def test_duplicate_name_returns_409(self, client):
        from app.services.folders import FolderService

        with patch.object(
            FolderService,
            "create",
            side_effect=AppException("Folder 'Work' already exists", 409, ErrorCode.DUPLICATE_ENTRY),
        ):
            resp = client.post("/api/folders/", json={"name": "Work"})

        assert resp.status_code == 409


class TestGetFolderEndpoint:
    def test_not_found_returns_404(self, client):
        from app.services.folders import FolderService

        with patch.object(
            FolderService,
            "get",
            side_effect=AppException("Folder not found", 404, ErrorCode.NOT_FOUND),
        ):
            resp = client.get(f"/api/folders/{uuid4()}")

        assert resp.status_code == 404

    def test_success(self, client):
        from app.services.folders import FolderService

        folder = make_folder()
        with patch.object(FolderService, "get", return_value=folder):
            resp = client.get(f"/api/folders/{folder.id}")

        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == folder.name


class TestUpdateFolderEndpoint:
    def test_success(self, client):
        from app.services.folders import FolderService

        folder = make_folder(name="Updated")
        with patch.object(FolderService, "update", return_value=folder):
            resp = client.patch(f"/api/folders/{folder.id}", json={"name": "Updated"})

        assert resp.status_code == 200

    def test_requires_auth(self, unauthed_client):
        resp = unauthed_client.patch(f"/api/folders/{uuid4()}", json={"name": "X"})
        assert resp.status_code == 401


class TestDeleteFolderEndpoint:
    def test_success(self, client):
        from app.services.folders import FolderService

        folder = make_folder()
        with patch.object(FolderService, "delete", return_value=None):
            resp = client.delete(f"/api/folders/{folder.id}")

        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_requires_auth(self, unauthed_client):
        resp = unauthed_client.delete(f"/api/folders/{uuid4()}")
        assert resp.status_code == 401
