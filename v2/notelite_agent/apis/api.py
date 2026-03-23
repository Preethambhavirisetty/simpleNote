import secrets

from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from apis.schema import IngestionRequest, RetrieveRequest
from apis.worker import ingest_in_background, worker_app
from core.config import AGENT_API_KEY
from core.contracts import AccessContext
from services.storage_service import VectorStore
from llama_index.core import Settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _require_api_key(key: str | None = Security(_api_key_header)) -> None:
    """Reject requests that don't carry the correct shared secret."""
    if not key or not secrets.compare_digest(key, AGENT_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )


router = APIRouter(
    prefix="/api",
    tags=["ingestion", "retrieval"],
    dependencies=[Depends(_require_api_key)],   # applied to every route in this router
)


@router.get("/status/{task_id}")
def get_status(task_id: str):
    result = worker_app.AsyncResult(task_id)
    inspector = worker_app.control.inspect(timeout=1.0)
    active_workers = inspector.ping() or {}
    worker_available = len(active_workers) > 0

    state = result.state
    diagnostics = None
    if state == "PENDING" and not worker_available:
        diagnostics = "No active Celery workers detected."

    return {
        "status": state,
        "result": result.result if result.ready() else None,
        "worker_available": worker_available,
        "diagnostics": diagnostics,
    }


@router.post('/ingest')
def ingest_data_to_vector_store(request: IngestionRequest):
    """
    {
        "user_id": "SAMPLEUSER01",
        "role": "user",
        "tenant_id": "TENANT01",
        "folder_id": "SAMPLESFOLDER01",
        "note_id": "SAMPLENOTE01",
        "folder_title": "SAMPLE FOLDER TITLE1",
        "note_title": "SAMPLE NOTE TITLE1",
        "description": "SAMPLE DESCRIPTION 1",
        "tags": [
            "tag1",
            "tag2"
        ],
      "text": "The \"System Failure\" Stress Test\ntext\nUPLOADED_FILE_FINAL_v2_USE_THIS_ONE.txt\nUser: @Marketing_Lead | Date: 2026-05-12\n\n\n1. CAMPAIGN OVERVIEW\nWe are launching \"Project Zenith.\" It's going to be huge.\n   \n   \n2. AUDIENCE SEGMENTATION (DRAFT)\n* Tier 1: Early Adopters\n    - Age: 18-24\n    - Interest: Tech, AI, \"Crypto\"\n        * Note: Re-verify the crypto segment.\n* Tier 2: Enterprise\n    - Size: 500+ Employees\n\n3. TRACKING PIXEL CODE\nAdd this to the <head> of the landing page:\n\n```javascript\n// Do not modify the ID below\nconst pixelId = \"PX-9900-ALPHA\";\nconsole.log(\"Pixel Initialized for \" + pixelId);\n/* \n  Fallback logic for legacy \n  browsers starts here \n*/\ninit_fallback();\nUse code with caution.\n```\n\nBUDGET BREAKDOWN (PASTED FROM EXCEL)\nCategory Amount Status Owner\nAds $50,000 Approved @John\nSocial $12,000 Pending @Sarah\nInfluencers $30,000 Review @Mike\nOFFICE LOCATIONS & HOURS\nHeadquarters: 555 Innovation Drive\nFloor 12, Suite 400\nAustin, TX 78701\nHours: 9am - 6pm (Mon-Fri)\nTO-DO LIST\nDesign the logo\nHire a copywriter\nPrepare the @Legal_Team brief\nRANDOM THOUGHTS...\nMaybe we should use more blue? Or teal?\nUpdate: Blue is confirmed.\n[END OF TRANSMISSION]"
    }
    """
    print(f"Ingesting note for: {request.user_id}!")
    data = request.to_ingestion_payload()
    # job = ingest_in_background.apply_async(args=[data])
    job = ingest_in_background.delay(data)
    return {"job_id": job.id}


@router.post('/get-context')
def get_context(request: RetrieveRequest):
    access_context = AccessContext(
        user_id=request.user_id,
        role=request.role,
        tenant_id=request.tenant_id,
    )
    with VectorStore() as db:
        results = db.retrieve_documents(
            request.query,
            k=request.k,
            access_context=access_context,
        )

    context = "\n\n".join(doc.text for doc in results)
    return {"context": context}


@router.post('/retrieve')
def ask_llm(request: RetrieveRequest):
    access_context = AccessContext(
        user_id=request.user_id,
        role=request.role,
        tenant_id=request.tenant_id,
    )
    with VectorStore() as db:
        results = db.retrieve_documents(
            request.query,
            k=request.k,
            access_context=access_context,
        )

    context = "\n\n".join(doc.text for doc in results)
    prompt = (
        "System: You are a factual assistant. Answer the Question using ONLY the provided Context. "
        "If the answer is not explicitly in the context, respond with: 'I am sorry, but I do not have enough information in your blogs to answer that.'\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {request.query}\n"
        "Answer:"
    )
    response = Settings.llm.complete(prompt)
    return response.text
