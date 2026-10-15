"""Shared agent state passed between graph nodes."""

from typing import Any, TypedDict

from app.core.enums import QueryComplexity, RetrievalStrategy
from app.schemas.agent import AgentPlan, ComplexityResult, IntentResult, ToolResult
from app.schemas.chat import ActionProposal, ChatMessage
from app.schemas.common import LatencyBreakdown, TokenUsage
from app.schemas.retrieval import Citation, RetrievedChunk


class AgentState(TypedDict, total=False):
    """LangGraph state. Partial updates replace listed keys; no infinite append reducer.

    Messages are compressed explicitly in the memory node instead of Annotated[add]
    so the graph cannot silently blow the 128k budget.
    """

    trace_id: str
    session_id: str
    user_id: str
    user_query: str
    messages: list[ChatMessage]
    summary: str
    intent: IntentResult | None
    complexity: ComplexityResult | None
    strategy: RetrievalStrategy | None
    query_complexity: QueryComplexity | None
    rewritten_queries: list[str]
    retrieved_chunks: list[RetrievedChunk]
    plan: AgentPlan | None
    tool_results: list[ToolResult]
    pending_action: ActionProposal | None
    confirmed_action: ActionProposal | None
    confirm_action_id: str | None
    idempotency_key: str | None
    final_answer: str | None
    citations: list[Citation]
    refused: bool
    error: str | None
    step_count: int
    token_usage: TokenUsage
    latency: LatencyBreakdown
    extra: dict[str, Any]
