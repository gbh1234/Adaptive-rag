"""Shared API response primitives."""

from typing import Any

from pydantic import BaseModel

from app.core.error_codes import ErrorCode


class APIErrorBody(BaseModel):
    error_code: ErrorCode
    message: str
    trace_id: str
    details: dict[str, Any] | None = None


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LatencyBreakdown(BaseModel):
    intent_ms: float = 0.0
    routing_ms: float = 0.0
    retrieval_ms: float = 0.0
    rerank_ms: float = 0.0
    tool_ms: float = 0.0
    llm_ms: float = 0.0
    total_ms: float = 0.0
