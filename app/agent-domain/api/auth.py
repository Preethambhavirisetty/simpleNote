import hmac
from typing import Annotated

from fastapi import Header, HTTPException, status

from config import DOMAIN_API_KEY


def require_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    if x_api_key is None or not hmac.compare_digest(x_api_key, DOMAIN_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
