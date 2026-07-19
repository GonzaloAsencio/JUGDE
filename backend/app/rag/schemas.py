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


class Usage(BaseModel):
    """Token spend of one query. Additive: components (HyDE arm, generation,
    retry attempts) sum with ``+``; a single estimated component marks the
    whole sum estimated, so a consumer can always tell measured from guessed."""

    prompt_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated: bool = False

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            estimated=self.estimated or other.estimated,
        )


class Citation(BaseModel):
    section: str
    source_type: str
    content_preview: str  # first 200 chars of chunk content
    similarity: float
    chunk_id: Optional[str] = None
    set: Optional[str] = None  # expansión del chunk (origins/spiritforged/unleashed/core)
    rule_codes: list[str] = Field(default_factory=list)  # rule codes covered by the full chunk


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
    latency_ms: int
    cache_hit: bool = False
    confidence: float = 0.0
    # None on cache hits (nothing was spent) and for pre-usage cached entries.
    usage: Optional[Usage] = None
