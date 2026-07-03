from typing import Optional

from pydantic import BaseModel, Field


class FolderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    is_pinned: bool = False


class FolderUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=150)
    is_pinned: Optional[bool] = None
