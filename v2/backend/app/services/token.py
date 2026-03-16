import jwt
from jwt import PyJWTError
from datetime import datetime, timezone, timedelta
from typing import Any
from app.core.config import SECRET_KEY, HASH_ALGORITHM
from fastapi.responses import Response
from app.exceptions.base import AppException
from app.schema.base import ErrorCode


class TokenService:
    def create_access_token(self, data: dict, expires_in: timedelta | None = None) -> str:
        data_encode = data.copy()
        token_expiry = datetime.now(timezone.utc) + (expires_in or timedelta(days=1))
        data_encode.update({"exp": token_expiry})
        return jwt.encode(data_encode, SECRET_KEY, algorithm=HASH_ALGORITHM)

    def create_assign_http_only_cookie(self, response: Response, user_id) -> bool:
        try:
            token_expires_in = timedelta(days=2)
            token = self.create_access_token(data={"sub": str(user_id)}, expires_in=token_expires_in)
            cookie_ttl_seconds = int(token_expires_in.total_seconds())
            response.set_cookie(
                key="access_token",
                value=f"Bearer {token}",
                httponly=True,
                max_age=cookie_ttl_seconds,
                expires=cookie_ttl_seconds,
                samesite="lax",
                secure=False,
            )
            return True
        except Exception:
            return False

    def decode_jwt_token(self, token: str) -> dict[str, Any]:
        try:
            bearer_prefix = "Bearer "
            if token.startswith(bearer_prefix):
                token = token[len(bearer_prefix):]
            return jwt.decode(token, SECRET_KEY, algorithms=[HASH_ALGORITHM])
        except PyJWTError:
            raise AppException(
                message="Invalid or expired token",
                status_code=401,
                error_code=ErrorCode.UNAUTHORIZED
            )
