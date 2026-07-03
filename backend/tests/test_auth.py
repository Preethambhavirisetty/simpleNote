"""
Tests for authentication: AuthService unit tests and /api/auth/* endpoints.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.exceptions.base import AppException
from app.schema.base import ErrorCode
from app.schema.users import UserLoginRequest, UserRegisterRequest
from tests.conftest import make_user

# ── AuthService unit tests ────────────────────────────────────────────────────

@pytest.fixture
def auth_service():
    from app.services.auth import AuthService

    svc = AuthService()
    svc.user_repo = MagicMock()
    svc.token_service = MagicMock()
    svc.token_service.create_assign_http_only_cookie.return_value = True
    return svc


class TestAuthServiceRegister:
    def test_register_success(self, auth_service, mock_db):
        new_user = make_user()
        auth_service.user_repo.get_by_email.return_value = None
        auth_service.user_repo.create.return_value = new_user
        mock_db.refresh.return_value = None

        payload = UserRegisterRequest(
            name="Test User",
            email="test@example.com",
            password="Test123",
        )
        result = auth_service.register_user(mock_db, payload, MagicMock())

        assert result["email"] == new_user.email
        assert "hashed_password" not in result
        auth_service.user_repo.create.assert_called_once()

    def test_register_duplicate_email_raises_400(self, auth_service, mock_db):
        auth_service.user_repo.get_by_email.return_value = make_user()

        payload = UserRegisterRequest(
            name="Another",
            email="exists@example.com",
            password="Test123",
        )
        with pytest.raises(AppException) as exc:
            auth_service.register_user(mock_db, payload, MagicMock())

        assert exc.value.status_code == 400
        assert exc.value.error_code == ErrorCode.REGISTRATION_FAILED

    def test_register_cookie_failure_raises_400(self, auth_service, mock_db):
        new_user = make_user()
        auth_service.user_repo.get_by_email.return_value = None
        auth_service.user_repo.create.return_value = new_user
        auth_service.token_service.create_assign_http_only_cookie.return_value = False

        payload = UserRegisterRequest(
            name="Test",
            email="test@example.com",
            password="Test123",
        )
        with pytest.raises(AppException) as exc:
            auth_service.register_user(mock_db, payload, MagicMock())

        assert exc.value.status_code == 400


class TestAuthServiceLogin:
    def test_login_success(self, auth_service, mock_db):
        existing = make_user()
        auth_service.user_repo.get_by_email.return_value = existing

        with patch("app.services.auth.check_password", return_value=True):
            payload = UserLoginRequest(email=existing.email, password="Test123")
            result = auth_service.login_user(mock_db, payload, MagicMock())

        assert result["email"] == existing.email

    def test_login_email_not_found_raises_400(self, auth_service, mock_db):
        auth_service.user_repo.get_by_email.return_value = None

        payload = UserLoginRequest(email="ghost@example.com", password="Test123")
        with pytest.raises(AppException) as exc:
            auth_service.login_user(mock_db, payload, MagicMock())

        assert exc.value.status_code == 400
        assert exc.value.error_code == ErrorCode.INVALID_CREDENTIALS

    def test_login_wrong_password_raises_400(self, auth_service, mock_db):
        auth_service.user_repo.get_by_email.return_value = make_user()

        with patch("app.services.auth.check_password", return_value=False):
            payload = UserLoginRequest(email="test@example.com", password="WrongPass1")
            with pytest.raises(AppException) as exc:
                auth_service.login_user(mock_db, payload, MagicMock())

        assert exc.value.status_code == 400
        assert exc.value.error_code == ErrorCode.INVALID_CREDENTIALS


# ── Auth endpoint tests ───────────────────────────────────────────────────────

class TestRegisterEndpoint:
    def test_success(self, client):
        from app.services.auth import AuthService

        mock_result = {"name": "Test", "email": "test@example.com", "role": ["standard_user"], "is_active": True}
        with patch.object(AuthService, "register_user", return_value=mock_result):
            resp = client.post(
                "/api/auth/register",
                json={"name": "Test", "email": "test@example.com", "password": "Test123"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["email"] == "test@example.com"

    def test_invalid_email_returns_422(self, client):
        resp = client.post(
            "/api/auth/register",
            json={"name": "Test", "email": "not-an-email", "password": "Test123"},
        )
        assert resp.status_code == 422
        assert resp.json()["success"] is False

    def test_short_password_returns_422(self, client):
        resp = client.post(
            "/api/auth/register",
            json={"name": "Test", "email": "test@example.com", "password": "abc"},
        )
        assert resp.status_code == 422

    def test_all_lowercase_password_returns_422(self, client):
        resp = client.post(
            "/api/auth/register",
            json={"name": "Test", "email": "test@example.com", "password": "lowercase1"},
        )
        assert resp.status_code == 422

    def test_all_alpha_password_returns_422(self, client):
        resp = client.post(
            "/api/auth/register",
            json={"name": "Test", "email": "test@example.com", "password": "ALLALPHA"},
        )
        assert resp.status_code == 422

    def test_missing_name_returns_422(self, client):
        resp = client.post(
            "/api/auth/register",
            json={"email": "test@example.com", "password": "Test123"},
        )
        assert resp.status_code == 422

    def test_duplicate_email_returns_400(self, client):
        from app.services.auth import AuthService

        with patch.object(
            AuthService,
            "register_user",
            side_effect=AppException("User with this email already exists", 400, ErrorCode.REGISTRATION_FAILED),
        ):
            resp = client.post(
                "/api/auth/register",
                json={"name": "Test", "email": "exists@example.com", "password": "Test123"},
            )

        assert resp.status_code == 400
        assert resp.json()["success"] is False


class TestLoginEndpoint:
    def test_success(self, client):
        from app.services.auth import AuthService

        mock_result = {"name": "Test", "email": "test@example.com", "role": ["standard_user"], "is_active": True}
        with patch.object(AuthService, "login_user", return_value=mock_result):
            resp = client.post(
                "/api/auth/login",
                json={"email": "test@example.com", "password": "Test123"},
            )

        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_missing_email_returns_422(self, client):
        resp = client.post("/api/auth/login", json={"password": "Test123"})
        assert resp.status_code == 422

    def test_invalid_credentials_returns_400(self, client):
        from app.services.auth import AuthService

        with patch.object(
            AuthService,
            "login_user",
            side_effect=AppException("Invalid email or password", 400, ErrorCode.INVALID_CREDENTIALS),
        ):
            resp = client.post(
                "/api/auth/login",
                json={"email": "bad@example.com", "password": "WrongPass1"},
            )

        assert resp.status_code == 400
        assert resp.json()["success"] is False


class TestLogoutEndpoint:
    def test_requires_auth(self, unauthed_client):
        resp = unauthed_client.delete("/api/auth/logout")
        assert resp.status_code == 401

    def test_success(self, client):
        from app.services.auth import AuthService

        with patch.object(
            AuthService,
            "logout_user",
            return_value={"message": "successfully deleted cookie"},
        ):
            resp = client.delete("/api/auth/logout")

        assert resp.status_code == 200
        assert resp.json()["success"] is True


class TestChangePasswordEndpoint:
    def test_requires_auth(self, unauthed_client):
        resp = unauthed_client.patch(
            "/api/auth/change-password",
            json={"current_password": "OldPass1", "new_password": "NewPass1"},
        )
        assert resp.status_code == 401

    def test_success(self, client):
        from app.services.user import UserService

        with patch.object(UserService, "change_password", return_value=None):
            resp = client.patch(
                "/api/auth/change-password",
                json={"current_password": "OldPass1", "new_password": "NewPass1"},
            )

        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_weak_new_password_returns_422(self, client):
        resp = client.patch(
            "/api/auth/change-password",
            json={"current_password": "OldPass1", "new_password": "abc"},
        )
        assert resp.status_code == 422

    def test_wrong_current_password_returns_400(self, client):
        from app.services.user import UserService

        with patch.object(
            UserService,
            "change_password",
            side_effect=AppException("Current password is incorrect", 400, ErrorCode.INVALID_CREDENTIALS),
        ):
            resp = client.patch(
                "/api/auth/change-password",
                json={"current_password": "WrongOld1", "new_password": "NewPass1"},
            )

        assert resp.status_code == 400
