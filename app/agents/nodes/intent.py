"""Intent classification: rule fast path plus LLM classifier."""

from __future__ import annotations

import re

from app.agents.nodes.intent_overlay import apply_intent_overlay
from app.core.constants import PROMPT_VERSION_INTENT
from app.core.enums import IntentLabel
from app.core.exceptions import LLMOutputError, LLMProviderError
from app.prompts.intent import INTENT_SYSTEM, INTENT_USER
from app.providers.base import LLMProvider
from app.providers.fake import OfflineLLMProvider
from app.providers.json_parser import parse_model
from app.schemas.agent import IntentResult

_KEYWORD_RULES: list[tuple[tuple[str, ...], IntentLabel]] = [
    (("转人工", "人工客服"), IntentLabel.HUMAN_HANDOFF),
    (("你好", "您好", "hi", "hello"), IntentLabel.GREETING),
    (("物流", "快递", "运单", "到哪"), IntentLabel.LOGISTICS),
    (("退款进度", "钱什么时候到"), IntentLabel.REFUND),
    (("退货", "换货", "七天", "7天无理由"), IntentLabel.RETURN_EXCHANGE),
    (("取消订单", "不想要了"), IntentLabel.CANCEL_ORDER),
    (("优惠券", "满减", "包邮券"), IntentLabel.COUPON),
    (("推荐", "有什么类似"), IntentLabel.RECOMMENDATION),
    (("保修", "质保"), IntentLabel.FAQ_POLICY),
    (("投诉", "差评", "态度"), IntentLabel.COMPLAINT),
    (("订单", "我的单"), IntentLabel.ORDER_INQUIRY),
]


def rule_based_intent(query: str) -> IntentResult:
    lowered = query.lower()
    for keywords, label in _KEYWORD_RULES:
        if label == IntentLabel.GREETING:
            matched = bool(
                re.fullmatch(r"(?:你好|您好|hi|hello)[!！。．.\s]*", query.strip(), re.I)
            )
        else:
            matched = any(keyword.lower() in lowered for keyword in keywords)
        if matched:
            return IntentResult(
                label=label,
                confidence=0.72,
                rationale=f"keyword:{keywords[0]}",
                prompt_version="intent_rules_v1",
            )
    if any(word in query for word in ("总统", "选谁", "怎么造炸弹")):
        return IntentResult(
            label=IntentLabel.OUT_OF_SCOPE,
            confidence=0.9,
            rationale="blocked_topic",
            prompt_version="intent_rules_v1",
        )
    return IntentResult(
        label=IntentLabel.FAQ_POLICY,
        confidence=0.55,
        rationale="default_faq",
        prompt_version="intent_rules_v1",
    )


class IntentClassifier:
    def __init__(
        self,
        llm: LLMProvider,
        *,
        system_prompt: str = INTENT_SYSTEM,
        prompt_version: str = PROMPT_VERSION_INTENT,
        apply_overlay: bool = True,
    ) -> None:
        self._llm = llm
        self._system_prompt = system_prompt
        self._prompt_version = prompt_version
        self._apply_overlay = apply_overlay

    async def classify(self, query: str) -> IntentResult:
        fallback = rule_based_intent(query)
        if isinstance(self._llm, OfflineLLMProvider):
            return self._maybe_overlay(query, fallback)
        try:
            response = await self._llm.generate(
                [
                    {"role": "system", "content": self._system_prompt},
                    {
                        "role": "user",
                        "content": INTENT_USER.format(
                            query=query, prompt_version=self._prompt_version
                        ),
                    },
                ],
                temperature=0.0,
                max_tokens=256,
                response_format={"type": "json_object"},
            )
            parsed = parse_model(response.content, IntentResult)
            if not parsed.prompt_version:
                parsed.prompt_version = self._prompt_version
            return self._maybe_overlay(query, parsed)
        except (LLMProviderError, LLMOutputError):
            return self._maybe_overlay(query, fallback)

    def _maybe_overlay(self, query: str, parsed: IntentResult) -> IntentResult:
        if not self._apply_overlay:
            return parsed
        label, overlay_note = apply_intent_overlay(query, parsed.label)
        if overlay_note:
            parsed.label = label
            parsed.rationale = f"{parsed.rationale};{overlay_note}"
            parsed.confidence = max(parsed.confidence, 0.93)
        return parsed
