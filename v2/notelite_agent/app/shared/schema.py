from __future__ import annotations

from typing import Generic, Optional, TypeVar

from pydantic import BaseModel


T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Uniform envelope returned by every endpoint.

    Success:  {"success": true,  "data": {...}}
    Failure:  {"success": false, "error": "message"}
    """

    success: bool
    data: Optional[T] = None
    error: Optional[str] = None

    @classmethod
    def ok(cls, data: T) -> "ApiResponse[T]":
        return cls(success=True, data=data)

    @classmethod
    def fail(cls, error: str) -> "ApiResponse[None]":
        return cls(success=False, error=error)
