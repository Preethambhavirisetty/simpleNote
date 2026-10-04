"""
Tests for authentication: AuthService unit tests and /api/auth/* endpoints.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import jwt
import pytest
from pydantic import ValidationError

from app.core.config import HASH_ALGORITHM, JWT_AUDIENCE, JWT_ISSUER, SECRET_KEY
from app.exceptions.base import AppException
from app.schema.base import ErrorCode
from app.schema.users import MAX_PASSWORD_BYTES, UserLoginRequest, UserRegisterRequest
from tests.conftest import make_user

# ── TokenService cookie flags ─────────────────────────────────────────────────

class TestJwtClaims:
    def test_access_token_contains_expected_issuer_and_audience(self):
        from app.services.token import TokenService

        token = TokenService().create_access_token({"sub": "user-1"})
        payload = TokenService().decode_jwt_token(token)

        assert payload["iss"] == JWT_ISSUER
        assert payload["aud"] == JWT_AUDIENCE

    @pytest.mark.parametrize(
        ("issuer", "audience"),
        [
            ("another-environment", JWT_AUDIENCE),
            (JWT_ISSUER, "another-application"),
        ],
    )
    def test_access_token_rejects_wrong_issuer_or_audience(self, issuer, audience):
        from app.services.token import TokenService

        token = jwt.encode(
            {
                "sub": "user-1",
                "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
                "iss": issuer,
                "aud": audience,
            },
            SECRET_KEY,
            algorithm=HASH_ALGORITHM,
        )

        with pytest.raises(AppException):
            TokenService().decode_jwt_token(token)

    def test_rejects_token_from_before_password_change(self):
        from app.deps import auth as auth_dependency

        request = MagicMock()
        request.cookies = {"access_token": "Bearer old-token"}
        user = make_user(auth_version=2)

        with (
            patch.object(
                auth_dependency.token_service,
                "decode_jwt_token",
                return_value={"sub": str(user.id), "ver": 1},
            ),
            patch.object(auth_dependency.user_service, "get_user", return_value=user),
            pytest.raises(AppException) as exc,
        ):
            auth_dependency.get_current_user(request, MagicMock())

        assert exc.value.status_code == 401


class TestAuthCookieSecureFlag:
    """The auth cookie's Secure attribute must follow the COOKIE_SECURE setting."""

    def _set_cookie_header(self):
        from fastapi.responses import Response

        from app.services.token import TokenService

        response = Response()
        assert TokenService().create_assign_http_only_cookie(
            response, user_id="user-1", email="test@example.com", role=["standard_user"]
        )
        return response.headers["set-cookie"]

    def test_secure_attribute_set_when_enabled(self):
        with patch("app.services.token.COOKIE_SECURE", True):
            header = self._set_cookie_header()
        assert "secure" in header.lower()
        assert "httponly" in header.lower()

    def test_secure_attribute_absent_when_disabled_for_local_dev(self):
        with patch("app.services.token.COOKIE_SECURE", False):
            header = self._set_cookie_header()
        assert "secure" not in header.lower()
        assert "httponly" in header.lower()


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
    def test_register_rejects_password_over_bcrypt_limit(self):
        with pytest.raises(ValidationError, match="at most 72 characters"):
            UserRegisterRequest(
                name="Test User",
                email="test@example.com",
                password="A1" + "x" * (MAX_PASSWORD_BYTES - 1),
            )

    def test_register_rejects_multibyte_password_over_bcrypt_limit(self):
        with pytest.raises(ValidationError, match="72 UTF-8 bytes"):
            UserRegisterRequest(
                name="Test User",
                email="test@example.com",
                password="A1" + "é" * 36,
            )

    def test_register_success(self, auth_service, mock_db):
        new_user = make_user()
        auth_service.user_repo.get_by_email.return_value = None
        auth_service.user_repo.create.return_value = new_user
        mock_db.refresh.return_value = None

        payload = UserRegisterRequest(
            name="Test User",
            email="test@example.com",
            password="Test1234",
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
            password="Test1234",
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
            password="Test1234",
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

    def test_login_email_not_found_raises_401(self, auth_service, mock_db):
        auth_service.user_repo.get_by_email.return_value = None

        payload = UserLoginRequest(email="ghost@example.com", password="Test123")
        with pytest.raises(AppException) as exc:
            auth_service.login_user(mock_db, payload, MagicMock())

        assert exc.value.status_code == 401
        assert exc.value.error_code == ErrorCode.INVALID_CREDENTIALS

    def test_login_wrong_password_raises_401(self, auth_service, mock_db):
        auth_service.user_repo.get_by_email.return_value = make_user()

        with patch("app.services.auth.check_password", return_value=False):
            payload = UserLoginRequest(email="test@example.com", password="WrongPass1")
            with pytest.raises(AppException) as exc:
                auth_service.login_user(mock_db, payload, MagicMock())

        assert exc.value.status_code == 401
        assert exc.value.error_code == ErrorCode.INVALID_CREDENTIALS


# ── Auth endpoint tests ───────────────────────────────────────────────────────

class TestRegisterEndpoint:
    def test_success(self, client):
        from app.services.auth import AuthService

        mock_result = {"name": "Test", "email": "test@example.com", "role": ["standard_user"], "is_active": True}
        with patch.object(AuthService, "register_user", return_value=mock_result):
            resp = client.post(
                "/api/auth/register",
                json={"name": "Test", "email": "test@example.com", "password": "Test1234"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["email"] == "test@example.com"

    def test_invalid_email_returns_422(self, client):
        resp = client.post(
            "/api/auth/register",
            json={"name": "Test", "email": "not-an-email", "password": "Test1234"},
        )
        assert resp.status_code == 422
        assert resp.json()["success"] is False

    def test_seven_character_password_returns_422(self, client):
        resp = client.post(
            "/api/auth/register",
            json={"name": "Test", "email": "test@example.com", "password": "Test123"},
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
            json={"email": "test@example.com", "password": "Test1234"},
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
                json={"name": "Test", "email": "exists@example.com", "password": "Test1234"},
            )

        assert resp.status_code == 400
        assert resp.json()["success"] is False

    def test_rate_limits_registration_by_client(self, client):
        from app.services.auth import AuthService

        mock_result = {"name": "Test", "email": "test@example.com", "role": ["standard_user"], "is_active": True}
        with patch.object(AuthService, "register_user", return_value=mock_result):
            responses = [
                client.post(
                    "/api/auth/register",
                    headers={"X-Real-IP": "192.0.2.10"},
                    json={"name": "Test", "email": f"test{i}@example.com", "password": "Test1234"},
                )
                for i in range(6)
            ]

        assert [response.status_code for response in responses[:5]] == [200] * 5
        assert responses[5].status_code == 429
        assert responses[5].json()["error"]["code"] == ErrorCode.RATE_LIMITED


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
            side_effect=AppException("Invalid email or password", 401, ErrorCode.INVALID_CREDENTIALS),
        ):
            resp = client.post(
                "/api/auth/login",
                json={"email": "bad@example.com", "password": "WrongPass1"},
            )

        assert resp.status_code == 401
        assert resp.json()["success"] is False

    def test_rate_limits_login_by_client_and_email(self, client):
        from app.services.auth import AuthService

        with patch.object(
            AuthService,
            "login_user",
            side_effect=AppException("Invalid email or password", 401, ErrorCode.INVALID_CREDENTIALS),
        ):
            responses = [
                client.post(
                    "/api/auth/login",
                    headers={"X-Real-IP": "192.0.2.11"},
                    json={"email": "target@example.com", "password": "WrongPass1"},
                )
                for _ in range(6)
            ]

        assert [response.status_code for response in responses[:5]] == [401] * 5
        assert responses[5].status_code == 429
        assert responses[5].json()["error"]["code"] == ErrorCode.RATE_LIMITED


class TestLogoutEndpoint:
    def test_logout_deletes_cookie_with_matching_attributes(self):
        from fastapi.responses import Response

        from app.services.auth import AuthService

        response = Response()
        with patch("app.services.auth.COOKIE_SECURE", True):
            AuthService().logout_user(response)

        header = response.headers["set-cookie"].lower()
        assert "access_token=" in header
        assert "path=/" in header
        assert "samesite=lax" in header
        assert "secure" in header
        assert "httponly" in header

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
