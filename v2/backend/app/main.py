import time
import uuid
from contextlib import asynccontextmanager

import jwt
from structlog.contextvars import bind_contextvars, clear_contextvars

from fastapi import FastAPI, Request

from app.api.v1.api import api_router
from app.core.config import POSTGRES_DB_URL, SECRET_KEY, HASH_ALGORITHM
from app.db.postgres.session import dispose_postgres, init_postgres
from app.exceptions.handlers import register_exceptions
from app.logger import setup_logging, logger
from app.core.openapi import OPENAPI_TAGS, configure_openapi


@asynccontextmanager
async def lifespan(app: FastAPI):
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


def _extract_user_id(request: Request) -> str:
    """Best-effort user_id: JWT cookie > X-User-Id header > anonymous."""
    internal_uid = request.headers.get("x-user-id")
    if internal_uid:
        return internal_uid

    token = request.cookies.get("access_token")
    if token:
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[HASH_ALGORITHM])
            return payload.get("sub", "anonymous")
        except Exception:
            pass

    return "anonymous"


@app.middleware("http")
async def request_middleware(request: Request, call_next):
    clear_contextvars()
    trace_id = str(uuid.uuid4())
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


app.include_router(api_router)
