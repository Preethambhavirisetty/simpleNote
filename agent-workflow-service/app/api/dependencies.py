from fastapi import Header, HTTPException

from app.api.config import SERVICE_API_KEY


def require_api_key(x_api_key: str = Header(..., alias="X-API-Key")) -> None:
    if SERVICE_API_KEY and x_api_key != SERVICE_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
