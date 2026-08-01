from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1 import fields, ingest, logs, runs, stats
from app.core.config import get_settings
from app.core.db import get_engine

settings = get_settings()

app = FastAPI(
    title="Agent Log Tracker",
    version="1.0.0",
    description=(
        "Detailed per-run logging for an agent app. Every log line is stored in "
        "order; selected values are additionally tracked as queryable fields."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (ingest.router, runs.router, logs.router, fields.router, stats.router):
    app.include_router(router, prefix="/api/v1")


@app.get("/health", tags=["meta"])
def health() -> dict:
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "database": settings.mysql_database}
