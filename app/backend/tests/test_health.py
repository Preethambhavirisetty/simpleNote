"""Health endpoint contract.

The Docker HEALTHCHECK in backend/Dockerfile probes GET /api/health and requires
a 200 without authentication — this pins that contract so the path can't drift
out from under the container healthcheck again.
"""


class TestHealthEndpoint:
    def test_health_returns_200_without_auth(self, unauthed_client):
        resp = unauthed_client.get("/api/health")
        assert resp.status_code == 200

    def test_health_reports_ok(self, unauthed_client):
        assert unauthed_client.get("/api/health").json() == {"STATUS": "OK"}
