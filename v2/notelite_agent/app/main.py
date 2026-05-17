import time
import uuid
from contextlib import asynccontextmanager

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.services.ingestion.routes import router as ingestion_router
from app.services.chat.routes import router as chat_router
from app.core.settings import init_llama_index_settings
from app.shared.schema import ApiResponse


log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_llama_index_settings()
    yield


app = FastAPI(
    title="Notelite AI Service",
    version="0.1.0",
    lifespan=lifespan,
)


# ── Uniform error responses ────────────────────────────────────────────────────

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=ApiResponse.fail(str(exc.detail)).model_dump(),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = "; ".join(
        f"{' → '.join(str(loc) for loc in err['loc'])}: {err['msg']}"
        for err in exc.errors()
    )
    return JSONResponse(
        status_code=422,
        content=ApiResponse.fail(f"Validation error: {errors}").model_dump(),
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    log.error("unhandled_exception", path=request.url.path, exc_info=True)
    return JSONResponse(
        status_code=500,
        content=ApiResponse.fail("Internal server error").model_dump(),
    )


# ── Request logging middleware ─────────────────────────────────────────────────

@app.middleware("http")
async def request_middleware(request: Request, call_next):
    clear_contextvars()
    bind_contextvars(trace_id=str(uuid.uuid4()))

    start = time.monotonic()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round((time.monotonic() - start) * 1000, 2)
        log.error(
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

    if response.status_code >= 500:
        log.error("request", **log_kw)
    elif response.status_code >= 400:
        log.warning("request", **log_kw)
    else:
        log.info("request", **log_kw)

    return response


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health", response_model=ApiResponse[dict])
def health():
    return ApiResponse.ok({"status": "ok"})


app.include_router(ingestion_router)
app.include_router(chat_router)
