"""Prometheus metrics for HTTP request throughput, latency, and errors.

Recorded from the request middleware in app.main and exposed at GET /metrics.
"""

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests.",
    ["method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "path"],
)


def render_metrics() -> tuple[bytes, str]:
    """Return the current metrics exposition and its content type."""
    return generate_latest(), CONTENT_TYPE_LATEST
