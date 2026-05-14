from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


class Citation(BaseModel):
    section: str
    source_type: str
    content_preview: str  # first 200 chars of chunk content
    similarity: float


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
    latency_ms: int
