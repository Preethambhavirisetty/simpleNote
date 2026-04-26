import json
import os
import sys
from pathlib import Path

import pytest

BASE_URL = os.environ.get("INTENT_CLASSIFIER_URL", "http://127.0.0.1:3000").rstrip("/")

TEST_CASES_PATH = Path(__file__).resolve().parent / "classification_test_cases.json"

with TEST_CASES_PATH.open(encoding="utf-8") as _f:
    TEST_CASES = json.load(_f)


@pytest.fixture(scope="module")
def http_client():
    """Call the already-running API; does not import or start the FastAPI app."""
    try:
        import httpx
    except ModuleNotFoundError as exc:
        pytest.skip(
            f"httpx is required for integration tests ({exc}). "
            f"Current interpreter: {sys.executable}. "
            "Install with: python -m pip install httpx",
        )
    client = httpx.Client(base_url=BASE_URL, timeout=60.0)
    try:
        probe = client.get("/openapi.json")
        if probe.status_code >= 500:
            pytest.skip(f"Server at {BASE_URL} returned HTTP {probe.status_code}")
    except httpx.ConnectError:
        client.close()
        pytest.skip(
            f"No server listening at {BASE_URL}. "
            "Start it first (e.g. uvicorn app:app --port 3000), "
            "or set INTENT_CLASSIFIER_URL to your base URL.",
        )
    yield client
    client.close()


@pytest.mark.parametrize(
    "case",
    TEST_CASES,
    ids=[f"{i}:{c['input'][:50]}" for i, c in enumerate(TEST_CASES)],
)
def test_intent_classification(http_client, case):
    utterance = case["input"]
    expected = case["expected"]
    response = http_client.post("/api/classify-intent", json={"query": utterance})
    assert response.status_code == 200, response.text
    body = response.json()
    actual_intent = body.get("intent")
    assert actual_intent == expected, (
        f"query={utterance!r} expected={expected!r} got intent={actual_intent!r} full={body!r}"
    )
