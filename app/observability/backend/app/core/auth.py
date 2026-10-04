import hmac
from typing import Annotated

from fastapi import Header, HTTPException, status

from app.core.config import get_settings


def require_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    expected = get_settings().agentlog_api_key
    if x_api_key is None or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
