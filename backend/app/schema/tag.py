from pydantic import BaseModel, Field


class TagCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class TagUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
