from fastapi import APIRouter


router = APIRouter(prefix="/chat")

@router.post("/stream")
async def chat_stream(payload):
    return {"message": "success"}
