import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

_XSS_PATTERNS = re.compile(r"<script|javascript:|on\w+=", re.IGNORECASE)


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    card_mentions: list[str] = Field(default_factory=list, max_length=10)
    language: Literal["en", "es"] = "en"
    session_id: Optional[str] = Field(default=None, max_length=64)

    @field_validator("question")
    @classmethod
    def reject_xss(cls, v: str) -> str:
        if _XSS_PATTERNS.search(v):
            raise ValueError("Question contains disallowed patterns.")
        return v

    @field_validator("card_mentions", mode="before")
    @classmethod
    def validate_card_mentions(cls, v: list) -> list:
        for item in v:
            if not isinstance(item, str):
                raise ValueError("card_mentions items must be strings.")
            if len(item) > 100:
                raise ValueError("Each card mention must be at most 100 characters.")
        return v


class Citation(BaseModel):
    section: str
    source_type: str
    content_preview: str  # first 200 chars of chunk content
    similarity: float
    chunk_id: Optional[str] = None


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
    latency_ms: int
    cache_hit: bool = False
    confidence: float = 0.0
