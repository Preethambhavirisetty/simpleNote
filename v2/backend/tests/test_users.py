"""
Tests for UserService unit tests and /api/users/* endpoints.
"""
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.exceptions.base import AppException
from app.schema.base import ErrorCode
from app.schema.users import UserAssignRoles, UserChangePassword, UserUpdate
from tests.conftest import make_user


# ── UserService unit tests ────────────────────────────────────────────────────

@pytest.fixture
def user_service():
    from app.services.user import UserService

    svc = UserService()
    svc.user_repo = MagicMock()
    return svc


class TestUserServiceGetUser:
    def test_get_existing_user(self, user_service, mock_db):
        u = make_user()
        user_service.user_repo.get_by_id.return_value = u
        result = user_service.get_user(mock_db, u.id)
        assert result.id == u.id

    def test_get_nonexistent_user_raises_404(self, user_service, mock_db):
        user_service.user_repo.get_by_id.return_value = None
        with pytest.raises(AppException) as exc:
            user_service.get_user(mock_db, uuid4())
        assert exc.value.status_code == 404

    def test_invalid_uuid_string_raises_400(self, user_service, mock_db):
        with pytest.raises(AppException) as exc:
            user_service.get_user(mock_db, "not-a-uuid")
        assert exc.value.status_code == 400


class TestUserServiceUpdateUser:
    def test_update_success(self, user_service, mock_db):
        u = make_user()
        user_service.user_repo.get_by_id.return_value = u
        payload = UserUpdate(name="Updated Name")
        user_service.update_user(mock_db, u.id, payload)
        user_service.user_repo.update.assert_called_once_with(mock_db, u, payload)

    def test_update_nonexistent_raises_404(self, user_service, mock_db):
        user_service.user_repo.get_by_id.return_value = None
        with pytest.raises(AppException) as exc:
            user_service.update_user(mock_db, uuid4(), UserUpdate(name="X"))
        assert exc.value.status_code == 404


class TestUserServiceChangePassword:
    def test_correct_password_succeeds(self, user_service, mock_db):
        u = make_user(hashed_password="hashed")
        user_service.user_repo.get_by_id.return_value = u
        payload = UserChangePassword(current_password="OldPass1", new_password="NewPass1")

        with patch("app.services.user.check_password", return_value=True):
            user_service.change_password(mock_db, u.id, payload)

        user_service.user_repo.update_password.assert_called_once()

    def test_wrong_current_password_raises_400(self, user_service, mock_db):
        u = make_user(hashed_password="hashed")
        user_service.user_repo.get_by_id.return_value = u
        payload = UserChangePassword(current_password="WrongOld1", new_password="NewPass1")

        with patch("app.services.user.check_password", return_value=False):
            with pytest.raises(AppException) as exc:
                user_service.change_password(mock_db, u.id, payload)

        assert exc.value.status_code == 400
        assert exc.value.error_code == ErrorCode.INVALID_CREDENTIALS


class TestUserServiceRolesAndStatus:
    def test_assign_roles(self, user_service, mock_db):
        u = make_user()
        user_service.user_repo.get_by_id.return_value = u
        from app.schema.users import Role
        payload = UserAssignRoles(roles=[Role.ADMIN])
        user_service.assign_roles(mock_db, u.id, payload)
        user_service.user_repo.assign_roles.assert_called_once()

    def test_activate_user(self, user_service, mock_db):
        u = make_user(is_active=False)
        user_service.user_repo.get_by_id.return_value = u
        user_service.activate_user(mock_db, u.id)
        user_service.user_repo.set_active.assert_called_once_with(mock_db, u, True)

    def test_deactivate_user(self, user_service, mock_db):
        u = make_user(is_active=True)
        user_service.user_repo.get_by_id.return_value = u
        user_service.deactivate_user(mock_db, u.id)
        user_service.user_repo.set_active.assert_called_once_with(mock_db, u, False)


# ── User endpoint tests ───────────────────────────────────────────────────────

class TestGetMeEndpoint:
    def test_requires_auth(self, unauthed_client):
        resp = unauthed_client.get("/api/users/me")
        assert resp.status_code == 401

    def test_returns_own_profile(self, client, current_user):
        resp = client.get("/api/users/me")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["email"] == current_user.email
        assert "hashed_password" not in body["data"]


class TestUpdateMeEndpoint:
    def test_requires_auth(self, unauthed_client):
        resp = unauthed_client.patch("/api/users/me", json={"name": "New Name"})
        assert resp.status_code == 401

    def test_update_name(self, client, current_user):
        from app.services.user import UserService

        updated = make_user(id=current_user.id, name="New Name", email=current_user.email)
        with patch.object(UserService, "update_user", return_value=updated):
            resp = client.patch("/api/users/me", json={"name": "New Name"})

        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == "New Name"

    def test_empty_payload_is_accepted(self, client, current_user):
        from app.services.user import UserService

        with patch.object(UserService, "update_user", return_value=current_user):
            resp = client.patch("/api/users/me", json={})

        assert resp.status_code == 200


class TestDeleteMeEndpoint:
    def test_requires_auth(self, unauthed_client):
        resp = unauthed_client.delete("/api/users/me")
        assert resp.status_code == 401

    def test_delete_own_account(self, client):
        from app.services.user import UserService

        with patch.object(UserService, "delete_user", return_value=None):
            resp = client.delete("/api/users/me")

        assert resp.status_code == 200


class TestAdminEndpoints:
    def test_list_users_requires_admin(self, client):
        """Standard user gets 403."""
        from app.services.user import UserService

        with patch.object(UserService, "list_users", return_value=[]):
            resp = client.get("/api/users/")

        assert resp.status_code == 403

    def test_admin_can_list_users(self, admin_client):
        from app.services.user import UserService

        users = [make_user(), make_user()]
        with patch.object(UserService, "list_users", return_value=users):
            resp = admin_client.get("/api/users/")

        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 2

    def test_admin_get_user_by_id(self, admin_client):
        from app.services.user import UserService

        u = make_user()
        with patch.object(UserService, "get_user", return_value=u):
            resp = admin_client.get(f"/api/users/{u.id}")

        assert resp.status_code == 200
        assert resp.json()["data"]["email"] == u.email

    def test_admin_get_nonexistent_user_returns_404(self, admin_client):
        from app.services.user import UserService

        with patch.object(
            UserService,
            "get_user",
            side_effect=AppException("User not found", 404, ErrorCode.USER_NOT_FOUND),
        ):
            resp = admin_client.get(f"/api/users/{uuid4()}")

        assert resp.status_code == 404

    def test_admin_activate_user(self, admin_client):
        from app.services.user import UserService

        with patch.object(UserService, "activate_user", return_value=None):
            resp = admin_client.patch(f"/api/users/{uuid4()}/activate")

        assert resp.status_code == 200

    def test_admin_deactivate_user(self, admin_client):
        from app.services.user import UserService

        with patch.object(UserService, "deactivate_user", return_value=None):
            resp = admin_client.patch(f"/api/users/{uuid4()}/deactivate")

        assert resp.status_code == 200

    def test_admin_assign_roles(self, admin_client):
        from app.services.user import UserService

        u = make_user(role=["admin"])
        with patch.object(UserService, "assign_roles", return_value=u):
            resp = admin_client.patch(
                f"/api/users/{u.id}/roles",
                json={"roles": ["admin"]},
            )

        assert resp.status_code == 200
