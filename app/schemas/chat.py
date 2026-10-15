"""Chat request/response and action-proposal schemas."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.enums import IntentLabel, QueryComplexity, RetrievalStrategy, ToolRisk
from app.schemas.common import LatencyBreakdown, TokenUsage
from app.schemas.retrieval import Citation


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    name: str | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=64)
    user_id: str = Field(default="anonymous", min_length=1, max_length=64)
    stream: bool = False
    confirm_action_id: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=128)


class ActionProposal(BaseModel):
    action_id: str
    tool_name: str
    arguments: dict[str, Any]
    risk: ToolRisk
    summary: str


class ChatResponse(BaseModel):
    answer: str
    session_id: str
    trace_id: str
    intent: IntentLabel | None = None
    complexity: QueryComplexity | None = None
    strategy: RetrievalStrategy | None = None
    citations: list[Citation] = Field(default_factory=list)
    pending_action: ActionProposal | None = None
    refused: bool = False
    error_code: str | None = None
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    latency: LatencyBreakdown = Field(default_factory=LatencyBreakdown)
