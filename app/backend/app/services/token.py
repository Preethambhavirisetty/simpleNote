from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi.responses import Response
from jwt import PyJWTError

from app.core.config import COOKIE_SAMESITE, COOKIE_SECURE, HASH_ALGORITHM, JWT_AUDIENCE, JWT_ISSUER, SECRET_KEY
from app.exceptions.base import AppException
from app.schema.base import ErrorCode


class TokenService:
    def create_access_token(self, data: dict, expires_in: timedelta | None = None) -> str:
        data_encode = data.copy()
        token_expiry = datetime.now(timezone.utc) + (expires_in or timedelta(days=1))
        data_encode.update({"exp": token_expiry, "iss": JWT_ISSUER, "aud": JWT_AUDIENCE})
        return jwt.encode(data_encode, SECRET_KEY, algorithm=HASH_ALGORITHM)

    def create_assign_http_only_cookie(
        self, response: Response, user_id, email: str, role: list, auth_version: int = 0
    ) -> bool:
        try:
            data = {
                "sub": str(user_id),
                "email": email,
                "role": role,
                "ver": auth_version,
            }
            token_expires_in = timedelta(days=2)
            token = self.create_access_token(data=data, expires_in=token_expires_in)
            cookie_ttl_seconds = int(token_expires_in.total_seconds())
            response.set_cookie(
                key="access_token",
                value=f"Bearer {token}",
                httponly=True,
                max_age=cookie_ttl_seconds,
                expires=cookie_ttl_seconds,
                samesite=COOKIE_SAMESITE,
                secure=COOKIE_SECURE,
            )
            return True
        except Exception:
            return False

    def decode_jwt_token(self, token: str) -> dict[str, Any]:
        try:
            bearer_prefix = "Bearer "
            if token.startswith(bearer_prefix):
                token = token[len(bearer_prefix):]
            return jwt.decode(
                token,
                SECRET_KEY,
                algorithms=[HASH_ALGORITHM],
                issuer=JWT_ISSUER,
                audience=JWT_AUDIENCE,
                options={"require": ["exp", "iss", "aud"]},
            )
        except PyJWTError:
            raise AppException(
                message="Invalid or expired token",
                status_code=401,
                error_code=ErrorCode.UNAUTHORIZED
            )
