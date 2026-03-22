from fastapi import FastAPI
from apis.api import router as api_router
from core.settings import init_llama_index_settings


app = FastAPI(
    title="RAG Service",
    version="0.1.0",
    description="Ingestion and retrieval API for the RAG pipeline.",
)


@app.on_event("startup")
def on_startup():
    # Initialize LlamaIndex/embedding/LLM settings once for the process.
    init_llama_index_settings()


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(api_router)