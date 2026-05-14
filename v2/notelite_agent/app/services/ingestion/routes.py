from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.dependencies import get_postgres_db, get_qdrant_store
from app.services.ingestion.storage.vector_store import QdrantVectorStore

router = APIRouter(prefix="/api/ingest")

@router.get("/health")
async def ingestion_pipeline_health_check(
    db: Session=Depends(get_postgres_db),
    vector_store: QdrantVectorStore=Depends(get_qdrant_store)
):
    is_pgsql_active = "inactive"
    is_qdrant_active = "inactive"
    try:
        db.execute(text("select 1"))
        is_pgsql_active = "active"
    except Exception as e:
        print(f"Failed to connect to Postgresql DB: {str(e)}")

    try:
        vector_store.get_collections()
        is_qdrant_active = "active"
    except Exception as e:
        print(f"Failed to connect to Qdrant: {str(e)}")
    
    return {
        "routes": "active",
        "postgresql_db": is_pgsql_active,
        "Qdrant_db": is_qdrant_active
    }

@router.post("/")
async def ingest_notes(payload, db: Session=Depends(get_postgres_db)):
    res = db.execute(text("select 1"))
    print(res)
    return {"message": "success"}

@router.post("/{job_id}")
async def ingest_notes(job_id):
    return {"message": f"Job id: {job_id} in progress"}