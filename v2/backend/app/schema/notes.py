from typing import List
from uuid import UUID, uuid4
from beanie import Document
from datetime import datetime, timezone
from pydantic import Field, ConfigDict


class Notes(Document):
    id: UUID = Field(default_factory=uuid4, alias="_id")  # type: ignore[assignment]
    user_id: UUID
    title: str
    isMemoryIncluded: bool = False
    isPinned: bool = False
    tags: List[str] = Field(default_factory=list)
    createdAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updatedAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True
    )
    class Settings:
        name = "notes"