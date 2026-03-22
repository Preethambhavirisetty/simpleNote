import hashlib
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class IngestionRequest(BaseModel):
    userid: str = Field(..., example="SAMPLEUSER01")
    role: str = Field("user", example="user")
    tenant_id: Optional[str] = Field(None, example="TENANT01")
    folder_id: str = Field(..., example="SAMPLESFOLDER01")
    note_id: str = Field(..., example="SAMPLENOTE01")
    folder_title: str = Field(..., min_length=1, example="SAMPLE FOLDER TITLE1")
    note_title: str = Field(..., min_length=1, example="SAMPLE NOTE TITLE1")
    description: Optional[str] = Field(None, example="SAMPLE DESCRIPTION 1")
    tags: List[str] = Field(default_factory=list, example=["tag1", "tag2"])
    text: str = Field(..., min_length=1, example="Sample text for ingestion")

    @field_validator('tags')
    @classmethod
    def validate_tags(cls, v: List[str]) -> List[str]:
        """Ensures tags are clean and unique."""
        return list(set(tag.strip().lower() for tag in v if tag.strip()))

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
            raise ValueError("tenant_id is required for non-admin ingestion requests.")
        return v

    def to_ingestion_payload(self) -> dict:
        """Transforms request to ingestion payload used by chunking/storage pipeline."""
        return {
            "userid": self.userid,
            "role": self.role,
            "tenant_id": self.tenant_id,
            "folder_id": self.folder_id,
            "note_id": self.note_id,
            "folder_title": self.folder_title,
            "note_title": self.note_title,
            "description": self.description or "",
            "tags": self.tags,
            "text": self.text,
        }

    def generate_stable_id(self, chunk_index: int) -> str:
        """Generates a consistent hash for Qdrant upserts."""
        base_string = f"{self.userid}_{self.folder_id}_{self.note_id}_{chunk_index}"
        return hashlib.sha256(base_string.encode()).hexdigest()


class RetrieveRequest(BaseModel):
    query: str = Field(...)
    k: int = Field(5, ge=1, le=50)
    userid: str = Field(..., example="SAMPLEUSER01")
    role: str = Field("user", example="user")
    tenant_id: Optional[str] = Field(None, example="TENANT01")

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
            raise ValueError("tenant_id is required for non-admin retrieval requests.")
        return v


