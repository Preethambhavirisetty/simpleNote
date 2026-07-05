"""Log-attribution user id extraction (app.main._extract_user_id).

Cookie-authenticated requests must resolve to the real user id (the cookie value
carries a "Bearer " prefix), and X-User-Id must be trusted only from internal
callers that present the shared internal key.
"""
from types import SimpleNamespace
from unittest.mock import patch

from app.main import _extract_user_id
from app.services.token import TokenService


INTERNAL_KEY = "test-internal-key"


def make_request(cookies=None, headers=None):
    return SimpleNamespace(cookies=cookies or {}, headers=headers or {})


def bearer_cookie(sub="user-42"):
    token = TokenService().create_access_token({"sub": sub})
    return {"access_token": f"Bearer {token}"}


class TestCookieExtraction:
    def test_bearer_prefixed_cookie_resolves_to_user_id(self):
        request = make_request(cookies=bearer_cookie(sub="user-42"))
        assert _extract_user_id(request) == "user-42"

    def test_invalid_cookie_is_anonymous(self):
        request = make_request(cookies={"access_token": "Bearer not-a-jwt"})
        assert _extract_user_id(request) == "anonymous"

    def test_no_credentials_is_anonymous(self):
        assert _extract_user_id(make_request()) == "anonymous"


class TestInternalHeaderTrust:
    def test_x_user_id_alone_is_ignored(self):
        request = make_request(headers={"x-user-id": "spoofed-user"})
        assert _extract_user_id(request) == "anonymous"

    def test_x_user_id_with_wrong_key_is_ignored(self):
        request = make_request(
            headers={"x-user-id": "spoofed-user", "x-internal-key": "wrong-key"}
        )
        with patch("app.main.AGENT_API_KEY", INTERNAL_KEY):
            assert _extract_user_id(request) == "anonymous"

    def test_x_user_id_with_valid_internal_key_is_trusted(self):
        request = make_request(
            headers={"x-user-id": "agent-user", "x-internal-key": INTERNAL_KEY}
        )
        with patch("app.main.AGENT_API_KEY", INTERNAL_KEY):
            assert _extract_user_id(request) == "agent-user"

    def test_cookie_still_wins_when_header_is_untrusted(self):
        request = make_request(
            cookies=bearer_cookie(sub="real-user"),
            headers={"x-user-id": "spoofed-user"},
        )
        assert _extract_user_id(request) == "real-user"
