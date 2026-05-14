import time
import uuid

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

from fastapi import FastAPI, Request

from app.services.ingestion.routes import router as ingestion_router
from app.services.chat.routes import router as chat_router
from app.core.settings import is_llama_index_settings_initialized, init_llama_index_settings


log = structlog.get_logger()

app = FastAPI(
    title="Notelite AI Service",
    version="0.1.0"
)


@app.on_event("startup")
def on_startup():
    if not is_llama_index_settings_initialized():
        print("Llama settings haven't been initialized, initializing now!")
        init_llama_index_settings()


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


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(ingestion_router)
app.include_router(chat_router)
