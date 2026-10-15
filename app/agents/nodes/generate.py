"""Answer generation and refusal nodes."""

from __future__ import annotations

import json
import time

from pydantic import BaseModel, Field

from app.agents.state import AgentState
from app.core.enums import RetrievalStrategy
from app.core.exceptions import LLMOutputError, LLMProviderError
from app.prompts.answer import ANSWER_SYSTEM, ANSWER_USER
from app.providers.base import LLMProvider
from app.providers.fake import OfflineLLMProvider
from app.providers.json_parser import parse_model
from app.schemas.common import LatencyBreakdown, TokenUsage
from app.schemas.retrieval import Citation


class AnswerPayload(BaseModel):
    answer: str
    citation_chunk_ids: list[str] = Field(default_factory=list)
    refused: bool = False


async def generate_node(state: AgentState, llm: LLMProvider) -> dict:
    started = time.perf_counter()
    chunks = state.get("retrieved_chunks") or []
    tools = state.get("tool_results") or []
    if tools and all(not tool.success for tool in tools):
        return {
            "final_answer": "暂时无法查到相关业务数据，请核对订单号或稍后重试。",
            "citations": [],
        }
    pending = state.get("pending_action")
    if (state.get("extra") or {}).get("missing_order_id"):
        return {"final_answer": "请提供要处理的订单号，确认后我才能继续。", "citations": []}
    if pending:
        answer = pending.summary
        latency = state.get("latency") or LatencyBreakdown()
        latency.llm_ms = (time.perf_counter() - started) * 1000
        return {
            "final_answer": answer,
            "citations": [],
            "refused": False,
            "latency": latency,
        }
    evidence = (
        "\n\n".join(f"[{c.chunk_id}] {c.title}\n{c.content}" for c in chunks[:6]) or "(无检索结果)"
    )
    tool_text = json.dumps([t.model_dump() for t in tools], ensure_ascii=False) if tools else "(无)"
    intent = state.get("intent")
    strategy = state.get("strategy") or RetrievalStrategy.DIRECT
    if isinstance(llm, OfflineLLMProvider):
        answer, citation_ids = _offline_answer(state)
        citations = [
            Citation(
                document_id=chunk.document_id,
                title=chunk.title,
                chunk_id=chunk.chunk_id,
                section=chunk.section,
            )
            for chunk in chunks
            if chunk.chunk_id in citation_ids
        ]
        return {"final_answer": answer, "citations": citations, "refused": False}
    messages = [
        {"role": "system", "content": ANSWER_SYSTEM},
        {
            "role": "user",
            "content": ANSWER_USER.format(
                query=state["user_query"],
                intent=intent.label.value if intent else "unknown",
                strategy=strategy.value,
                evidence=evidence,
                tool_results=tool_text,
            ),
        },
    ]
    try:
        response = await llm.generate(
            messages,
            temperature=0.2,
            max_tokens=700,
            response_format={"type": "json_object"},
        )
        payload = parse_model(response.content, AnswerPayload)
        usage = response.usage
    except (LLMProviderError, LLMOutputError):
        payload = AnswerPayload(
            answer=_extractive_fallback(state["user_query"], evidence, tool_text),
            citation_chunk_ids=[chunks[0].chunk_id] if chunks else [],
        )
        usage = TokenUsage()
    citations = [
        Citation(
            document_id=chunk.document_id,
            title=chunk.title,
            chunk_id=chunk.chunk_id,
            section=chunk.section,
        )
        for chunk in chunks
        if chunk.chunk_id in set(payload.citation_chunk_ids)
    ]
    latency = state.get("latency") or LatencyBreakdown()
    latency.llm_ms = (time.perf_counter() - started) * 1000
    prev_usage = state.get("token_usage") or TokenUsage()
    merged = TokenUsage(
        prompt_tokens=prev_usage.prompt_tokens + usage.prompt_tokens,
        completion_tokens=prev_usage.completion_tokens + usage.completion_tokens,
        total_tokens=prev_usage.total_tokens + usage.total_tokens,
    )
    return {
        "final_answer": payload.answer,
        "citations": citations,
        "refused": payload.refused,
        "latency": latency,
        "token_usage": merged,
    }


async def refuse_node(state: AgentState) -> dict:
    return {
        "final_answer": "这个问题超出电商客服范围，我无法协助。如需购物、订单、物流或售后帮助，请换个问题。",
        "refused": True,
        "citations": [],
    }


def _extractive_fallback(query: str, evidence: str, tool_text: str) -> str:
    if evidence and evidence != "(无检索结果)":
        snippet = evidence.split("\n", 1)[-1][:240].strip()
        return f"暂时无法生成完整答复。相关资料节选：\n\n> {snippet}\n\n请以原文为准。"
    if tool_text and tool_text != "(无)":
        return "已查询到系统数据，但暂时无法可靠地整理答复。请稍后重试或转人工。"
    return "暂时无法基于现有信息给出可靠答复，请补充相关信息或转人工。"


def _offline_answer(state: AgentState) -> tuple[str, set[str]]:
    """Use only retrieved text or whitelisted tool fields when no LLM is configured."""
    strategy = state.get("strategy")
    if strategy == RetrievalStrategy.DIRECT:
        return "你好，我可以帮你查看商品政策、订单、物流和售后问题。", set()

    for result in reversed(state.get("tool_results") or []):
        if not result.success:
            continue
        data = result.output
        if result.name == "cancel_order":
            return f"订单 {data.get('order_id', '')} 已取消。", set()
        if result.name == "create_refund_request":
            return f"订单 {data.get('order_id', '')} 的退款申请已提交，尚不代表款项到账。", set()
        if result.name == "create_return_request":
            return f"订单 {data.get('order_id', '')} 的退货申请已提交，尚不代表退款完成。", set()
        if result.name == "get_order":
            status = {
                "created": "待支付",
                "paid": "已支付",
                "shipped": "已发货",
                "delivered": "已签收",
                "cancelled": "已取消",
                "refunding": "退款中",
                "refunded": "已退款",
            }.get(str(data.get("status")), "未知")
            return f"订单 {data.get('order_id', '')} 当前状态：{status}。", set()
        if result.name == "track_shipment":
            events = data.get("events") or []
            latest = events[-1] if events else None
            label = (
                {"warehouse": "仓库处理中", "in_transit": "运输中", "delivered": "已签收"}.get(
                    str(latest.get("status")), "状态未知"
                )
                if isinstance(latest, dict)
                else "暂无物流轨迹"
            )
            return f"订单 {data.get('order_id', '')} 的物流状态：{label}。", set()
        if result.name == "get_refund_status":
            refunds = data.get("refunds") or []
            if not refunds:
                return "这笔订单暂未查询到退款申请记录。", set()
            first = refunds[0]
            if isinstance(first, dict):
                return (
                    f"查询到退款单 {first.get('refund_id', '')}，当前状态：{first.get('status', '未知')}。",
                    set(),
                )
        if result.name == "search_knowledge":
            found = data.get("chunks") or []
            if found and isinstance(found[0], dict):
                item = found[0]
                title = str(item.get("title") or "相关政策")
                excerpt = str(item.get("content") or "").strip()[:260]
                return (
                    f"当前未配置生成模型。找到《{title}》中的资料节选，请核对原文：\n\n> {excerpt}",
                    set(),
                )

    chunks = state.get("retrieved_chunks") or []
    if chunks:
        chunk = chunks[0]
        excerpt = chunk.content.strip()[:260]
        return (
            f"当前未配置生成模型，以下是《{chunk.title}》的资料节选，请核对原文：\n\n> {excerpt}",
            {chunk.chunk_id},
        )
    return (
        "当前无法可靠回答这个问题。请补充相关信息，或联系人工客服。",
        set(),
    )
