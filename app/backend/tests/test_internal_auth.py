from unittest.mock import patch
from uuid import uuid4

import pytest

from app.deps.internal import verify_internal_user_id
from app.exceptions.base import AppException
from app.schema.base import ErrorCode

INTERNAL_KEY = "test-internal-key"


def test_internal_user_id_returns_valid_uuid():
    user_id = uuid4()

    with patch("app.deps.internal.AGENT_API_KEY", INTERNAL_KEY):
        assert verify_internal_user_id(INTERNAL_KEY, str(user_id)) == user_id


def test_internal_user_id_rejects_invalid_uuid_with_422():
    with patch("app.deps.internal.AGENT_API_KEY", INTERNAL_KEY), pytest.raises(
        AppException
    ) as exc_info:
        verify_internal_user_id(INTERNAL_KEY, "not-a-uuid")

    assert exc_info.value.status_code == 422
    assert exc_info.value.error_code == ErrorCode.VALIDATION_ERROR


def test_internal_key_is_validated_before_user_id():
    with patch("app.deps.internal.AGENT_API_KEY", INTERNAL_KEY), pytest.raises(
        AppException
    ) as exc_info:
        verify_internal_user_id("wrong-key", "not-a-uuid")

    assert exc_info.value.status_code == 401


def test_internal_endpoint_returns_422_for_invalid_user_id(client):
    with patch("app.deps.internal.AGENT_API_KEY", INTERNAL_KEY):
        response = client.get(
            "/api/notes/internal/",
            headers={"X-Internal-Key": INTERNAL_KEY, "X-User-Id": "not-a-uuid"},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == ErrorCode.VALIDATION_ERROR
