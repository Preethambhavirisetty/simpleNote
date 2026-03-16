import collections
from contextlib import asynccontextmanager
from typing import Any
from beanie import init_beanie
from fastapi import FastAPI, Request
from motor.motor_asyncio import AsyncIOMotorClient

from app.api.v1.api import api_router
from app.schema.notes import Notes
from app.schema.blocks import Blocks
from app.core.config import MONGO_DB_URL, COLLECTION_NAME, POSTGRES_DB_URL
from app.db.postgres.session import init_postgres, dispose_postgres
from app.exceptions.handlers import register_exceptions


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Postgres
    if POSTGRES_DB_URL:
        init_postgres(POSTGRES_DB_URL)

    # Mongo (Notes + Blocks)
    client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(MONGO_DB_URL)
    await init_beanie(
        database=client.get_database(COLLECTION_NAME),  # type: ignore[arg-type]
        document_models=[Notes, Blocks],
    )

    yield

    dispose_postgres()
    client.close()

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
