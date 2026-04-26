from pydantic import BaseModel
from typing import List, Literal, Optional


class IntentSchema(BaseModel):
    intent: str
    description: str
    keywords: Optional[List[str]] = None
    parent_intent: Optional[str] = None
    type: Optional[Literal["intent", "service"]] = None


class QuerySchema(BaseModel):
    query: str
    score_threshold: Optional[float] = 0.45