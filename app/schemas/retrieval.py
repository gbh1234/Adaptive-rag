"""Retrieved chunk and citation schemas."""

from pydantic import BaseModel, Field

from app.core.enums import DocumentCategory


class RetrievedChunk(BaseModel):
    chunk_id: str
    document_id: str
    title: str
    content: str
    score: float
    rank: int | None = None
    source: str = "hybrid"
    category: DocumentCategory = DocumentCategory.FAQ
    section: str | None = None
    chunk_index: int = 0
    policy_version: str = "v1"
    metadata: dict[str, str] = Field(default_factory=dict)


class Citation(BaseModel):
    document_id: str
    title: str
    chunk_id: str
    section: str | None = None


class RetrievalRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    category: DocumentCategory | None = None
