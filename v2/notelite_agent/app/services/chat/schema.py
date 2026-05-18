from typing import Optional
from pydantic import BaseModel, Field, field_validator

class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=10_000)
    k: int = Field(5, ge=1, le=50)
    user_id: str = Field(...)
    role: str = Field("user")
    tenant_id: Optional[str] = None
    conversation_id: Optional[str] = Field(None, description="Existing conversation to continue")
    conversation_title: Optional[str] = Field(None, max_length=255)

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        role = v.strip().lower()
        if role not in {"user", "admin"}:
            raise ValueError("role must be 'user' or 'admin'")
        return role

    @field_validator("tenant_id")
    @classmethod
    def validate_tenant_id(cls, v: Optional[str], info):
        role = (info.data.get("role") or "user").lower()
        if role != "admin" and not v:
            raise ValueError("tenant_id is required for non-admin requests.")
        return v