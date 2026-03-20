import collections
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.api.v1.api import api_router
from app.core.config import POSTGRES_DB_URL
from app.db.postgres.session import dispose_postgres, init_postgres
from app.exceptions.handlers import register_exceptions


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_postgres(POSTGRES_DB_URL)
    yield
    dispose_postgres()


app = FastAPI(lifespan=lifespan)

register_exceptions(app)

endpoint_hit_rate: collections.Counter[str] = collections.Counter()


@app.middleware("http")
async def track_requests(request: Request, call_next):
    endpoint = request.url.path
    endpoint_hit_rate[endpoint] += 1
    response = await call_next(request)
    return response


@app.get("/api/stats")
def get_stats():
    return endpoint_hit_rate


app.include_router(api_router)
