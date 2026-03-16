from enum import Enum
from uuid import UUID, uuid4
from beanie import Document
from datetime import datetime, timezone
from pydantic import Field, ConfigDict


class BlockType(str, Enum):
    PARAGRAPH = "paragraph"
    HEADING = "heading"
    BULLET_LIST = "BULLET_LIST"
    NUMBERED_LIST = "NUMBERED_LIST"
    IMAGE = "image"
    CODE = "CODE"
    QUOTE = "QUOTE"
    TABLE = "TABLE"


class Blocks(Document):
    id: UUID = Field(default_factory=uuid4, alias="_id")  # type: ignore[assignment]
    user_id: UUID
    note_id: UUID
    type: BlockType
    content: str
    order_index: float
    createdAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updatedAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True
    )
    class Settings:
        name="blocks"


"""
{
  "id": "b4",
  "type": "image",
  "content": {
    "url": "cdn/image.png",
    "caption": "Architecture"
  }
}

OR

{
  "_id": "block_1",
  "noteId": "note_1",
  "type": "paragraph",
  "content": { "text": "Discuss roadmap" },
  "position": 1
}
"""