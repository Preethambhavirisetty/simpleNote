from __future__ import annotations

import importlib

import pytest
from fastapi import HTTPException


def test_config_path_must_stay_inside_allowlisted_directory():
    from app.api.runtime import _resolve_config_path

    with pytest.raises(HTTPException) as exc_info:
        _resolve_config_path(None, "/etc/passwd")

    assert exc_info.value.status_code == 400


def test_inline_config_rejects_non_allowlisted_upstream_host(monkeypatch):
    import app.api.runtime as runtime

    monkeypatch.setattr(runtime, "ALLOWED_UPSTREAM_HOSTS", {"llm.internal"})

    with pytest.raises(HTTPException) as exc_info:
        runtime._validate_outbound_hosts(
            {
                "llm": {"base_url": "https://attacker.example/v1"},
                "mcp": {"servers": [{"url": "https://llm.internal/mcp"}]},
            }
        )

    assert exc_info.value.status_code == 400
    assert "attacker.example" in str(exc_info.value.detail)


def test_inline_config_accepts_allowlisted_upstream_hosts(monkeypatch):
    import app.api.runtime as runtime

    monkeypatch.setattr(runtime, "ALLOWED_UPSTREAM_HOSTS", {"llm.internal", "mcp.internal"})

    runtime._validate_outbound_hosts(
        {
            "llm": {"base_url": "https://llm.internal/v1"},
            "mcp": {"servers": [{"url": "https://mcp.internal/mcp"}]},
        }
    )


def test_api_key_dependency_fails_closed_when_key_missing(monkeypatch):
    import app.api.dependencies as dependencies

    monkeypatch.setattr(dependencies, "SERVICE_API_KEY", "")

    with pytest.raises(HTTPException) as exc_info:
        dependencies.require_api_key("anything")

    assert exc_info.value.status_code == 401


def test_api_key_dependency_uses_constant_time_match(monkeypatch):
    import app.api.dependencies as dependencies

    monkeypatch.setattr(dependencies, "SERVICE_API_KEY", "secret")

    dependencies.require_api_key("secret")
    with pytest.raises(HTTPException):
        dependencies.require_api_key("wrong")
