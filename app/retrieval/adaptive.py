"""Adaptive-RAG complexity routing.

Paper mapping (Jeong et al., ACL 2024):
- simple      -> DIRECT (no retrieval) or REFUSE
- single_hop  -> SINGLE (one-shot hybrid retrieval)
- multi_hop   -> MULTI  (Self-RAG iterative retrieval)
- tool needs  -> AGENT  (planner + tools, optional retrieval)

LLM classifier is preferred. Rule fallback keeps the system testable and
available when the model is down.
"""

from __future__ import annotations

import re

from app.core.constants import PROMPT_VERSION_COMPLEXITY
from app.core.enums import IntentLabel, QueryComplexity, RetrievalStrategy
from app.core.exceptions import LLMOutputError, LLMProviderError
from app.prompts.complexity import COMPLEXITY_SYSTEM, COMPLEXITY_USER
from app.providers.base import LLMProvider
from app.providers.fake import OfflineLLMProvider
from app.providers.json_parser import parse_model
from app.schemas.agent import ComplexityResult, IntentResult

_MULTI_HOP_CUES = (
    "同时",
    "并且",
    "还是",
    "如果",
    "但是已经",
    "过了",
    "既",
    "又",
    " besides",
    "and then",
)
_TOOL_CUES = (
    "订单",
    "物流",
    "快递",
    "运单",
    "退款进度",
    "取消订单",
    "我的单",
    "order",
    "tracking",
)
_ORDER_ID = re.compile(r"\b(?:ORD[-_]?\d{4,}|\d{12,})\b", re.IGNORECASE)


def rule_based_complexity(query: str, intent: IntentResult) -> ComplexityResult:
    text = query.strip()
    if intent.label == IntentLabel.OUT_OF_SCOPE:
        return ComplexityResult(
            complexity=QueryComplexity.OUT_OF_SCOPE,
            strategy=RetrievalStrategy.REFUSE,
            confidence=0.95,
            rationale="intent_out_of_scope",
        )
    if intent.label in {IntentLabel.GREETING, IntentLabel.CHITCHAT}:
        return ComplexityResult(
            complexity=QueryComplexity.SIMPLE,
            strategy=RetrievalStrategy.DIRECT,
            confidence=0.9,
            rationale="social_or_greeting",
        )
    policy_question = not _ORDER_ID.search(text) and any(
        cue in text
        for cue in (
            "规则",
            "政策",
            "条件",
            "怎么算",
            "可以吗",
            "能不能",
            "怎么退",
            "能退吗",
            "能取消吗",
        )
    )
    if policy_question and intent.label in {
        IntentLabel.CANCEL_ORDER,
        IntentLabel.REFUND,
        IntentLabel.RETURN_EXCHANGE,
    }:
        return ComplexityResult(
            complexity=QueryComplexity.SINGLE_HOP,
            strategy=RetrievalStrategy.SINGLE,
            confidence=0.78,
            rationale="general_policy_without_order",
        )
    transactional = intent.label in {
        IntentLabel.ORDER_INQUIRY,
        IntentLabel.LOGISTICS,
        IntentLabel.CANCEL_ORDER,
        IntentLabel.HUMAN_HANDOFF,
    }
    needs_account_data = intent.label in {IntentLabel.REFUND, IntentLabel.RETURN_EXCHANGE} and (
        bool(_ORDER_ID.search(text))
        or any(cue in text for cue in ("我的", "帮我退", "申请退款", "退款进度", "到账"))
    )
    if (
        transactional
        or needs_account_data
        or _ORDER_ID.search(text)
        or any(cue in text.lower() for cue in _TOOL_CUES)
    ):
        return ComplexityResult(
            complexity=QueryComplexity.TOOL_REQUIRED,
            strategy=RetrievalStrategy.AGENT,
            confidence=0.8,
            rationale="entity_or_transactional_intent",
        )
    hop_cues = sum(1 for cue in _MULTI_HOP_CUES if cue in text)
    if hop_cues >= 1 and len(text) > 18:
        return ComplexityResult(
            complexity=QueryComplexity.MULTI_HOP,
            strategy=RetrievalStrategy.MULTI,
            confidence=0.7,
            rationale="multi_constraint_query",
        )
    return ComplexityResult(
        complexity=QueryComplexity.SINGLE_HOP,
        strategy=RetrievalStrategy.SINGLE,
        confidence=0.75,
        rationale="single_policy_or_faq",
    )


class AdaptiveRouter:
    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def route(self, query: str, intent: IntentResult) -> ComplexityResult:
        fallback = rule_based_complexity(query, intent)
        if isinstance(self._llm, OfflineLLMProvider):
            return fallback
        try:
            response = await self._llm.generate(
                [
                    {"role": "system", "content": COMPLEXITY_SYSTEM},
                    {
                        "role": "user",
                        "content": COMPLEXITY_USER.format(
                            query=query,
                            intent=intent.label.value,
                            prompt_version=PROMPT_VERSION_COMPLEXITY,
                        ),
                    },
                ],
                temperature=0.0,
                max_tokens=256,
                response_format={"type": "json_object"},
            )
            parsed = parse_model(response.content, ComplexityResult)
            if (
                fallback.rationale == "general_policy_without_order"
                and parsed.strategy == RetrievalStrategy.AGENT
            ):
                return fallback
            if _ORDER_ID.search(query) and fallback.strategy == RetrievalStrategy.AGENT:
                return fallback
            return parsed
        except (LLMProviderError, LLMOutputError):
            return fallback
