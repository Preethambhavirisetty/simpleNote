import time
import collections
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.api.v1.api import api_router
from app.core.config import POSTGRES_DB_URL
from app.db.postgres.session import dispose_postgres, init_postgres
from app.exceptions.handlers import register_exceptions
from app.logger import setup_logging, logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_postgres(POSTGRES_DB_URL)
    yield
    dispose_postgres()


setup_logging()
app = FastAPI(lifespan=lifespan)

register_exceptions(app)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = round((time.time() - start) * 1000, 2)
    logger.info(
        "request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=duration,
        user_id=request.headers.get("x-user-id") # ??
    )

    return response



app.include_router(api_router)
