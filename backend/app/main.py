import time
import uuid
from contextlib import asynccontextmanager

from structlog.contextvars import bind_contextvars, clear_contextvars

from fastapi import FastAPI, Request, Response

from app.api.v1.api import api_router
from app.core.config import AGENT_API_KEY, NOTES_ENCRYPTION_KEY, POSTGRES_DB_URL
from app.core.feature_flags import is_enabled
from app.db.postgres.session import dispose_postgres, init_postgres
from app.deps.internal import internal_key_matches
from app.exceptions.handlers import register_exceptions
from app.logger import setup_logging, logger
from app.metrics import REQUEST_COUNT, REQUEST_LATENCY, render_metrics
from app.core.openapi import OPENAPI_TAGS, configure_openapi
from app.services.token import TokenService


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail fast: encryption enabled without a key would break every note write/read.
    if is_enabled("notes.encryption") and not NOTES_ENCRYPTION_KEY:
        raise RuntimeError("notes.encryption is enabled but NOTES_ENCRYPTION_KEY is not set.")
    init_postgres(POSTGRES_DB_URL)
    yield
    dispose_postgres()


setup_logging()
app = FastAPI(
    title="Notelite Backend API",
    description="Core API for authentication, notes, folders, tags, users, and conversations.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=OPENAPI_TAGS,
    swagger_ui_parameters={"displayRequestDuration": True, "filter": True, "persistAuthorization": True},
    lifespan=lifespan,
)
configure_openapi(app)

register_exceptions(app)


_token_service = TokenService()


def _extract_user_id(request: Request) -> str:
    """Best-effort user_id for log attribution: JWT cookie > trusted internal header.

    X-User-Id is honored only alongside a valid X-Internal-Key — otherwise any
    public client could stamp arbitrary user ids into the logs.
    """
    internal_uid = request.headers.get("x-user-id")
    internal_key = request.headers.get("x-internal-key")
    if internal_uid and internal_key_matches(internal_key, expected_key=AGENT_API_KEY):
        return internal_uid

    token = request.cookies.get("access_token")
    if token:
        try:
            # decode_jwt_token strips the "Bearer " prefix the auth cookie carries.
            payload = _token_service.decode_jwt_token(token)
            return payload.get("sub", "anonymous")
        except Exception:
            pass

    return "anonymous"


def _trusted_trace_id(request: Request) -> str:
    """Reuse an inbound trace id only from internal callers (valid X-Internal-Key).

    nginx also strips X-Trace-Id at the edge; this guards direct in-network calls
    so public clients can never inject arbitrary or colliding ids into the logs.
    """
    inbound = request.headers.get("x-trace-id")
    internal_key = request.headers.get("x-internal-key")
    if inbound and internal_key_matches(internal_key, expected_key=AGENT_API_KEY):
        return inbound
    return str(uuid.uuid4())


@app.middleware("http")
async def request_middleware(request: Request, call_next):
    clear_contextvars()
    trace_id = _trusted_trace_id(request)
    user_id = _extract_user_id(request)
    bind_contextvars(trace_id=trace_id, user_id=user_id)

    start = time.monotonic()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round((time.monotonic() - start) * 1000, 2)
        logger.error(
            "request_error",
            method=request.method,
            path=request.url.path,
            duration_ms=duration_ms,
            exc_info=True,
        )
        raise

    duration_ms = round((time.monotonic() - start) * 1000, 2)

    # Metrics: label by the matched route template (not the raw path) to bound cardinality.
    route = request.scope.get("route")
    path_label = getattr(route, "path", None) or "unmatched"
    if request.url.path != "/metrics":
        REQUEST_LATENCY.labels(request.method, path_label).observe((time.monotonic() - start))
        REQUEST_COUNT.labels(request.method, path_label, str(response.status_code)).inc()

    # Expose the correlation id so callers (and error reports) can be tied back to logs.
    response.headers["X-Trace-Id"] = trace_id

    log_kw = dict(
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=duration_ms,
    )
    if request.url.query:
        log_kw["query_string"] = str(request.url.query)

    if response.status_code >= 500:
        logger.error("request", **log_kw)
    elif response.status_code >= 400:
        logger.warning("request", **log_kw)
    else:
        logger.info("request", **log_kw)

    return response


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    """Prometheus scrape endpoint."""
    payload, content_type = render_metrics()
    return Response(content=payload, media_type=content_type)


app.include_router(api_router)
