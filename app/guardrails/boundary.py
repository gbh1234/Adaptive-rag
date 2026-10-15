"""Scope boundary check that rejects out-of-domain requests."""

from __future__ import annotations

from app.core.enums import IntentLabel
from app.core.error_codes import ErrorCode
from app.core.exceptions import GuardrailError

_BLOCKED_TOPICS = (
    "炸弹",
    "制毒",
    "枪支",
    "hack the",
    "信用卡盗",
    "验证码转发",
)


def assert_in_scope(query: str, intent: IntentLabel | None = None) -> None:
    lowered = query.lower()
    if any(topic in lowered for topic in _BLOCKED_TOPICS):
        raise GuardrailError("query is out of customer-service scope", ErrorCode.QUERY_OUT_OF_SCOPE)
    if intent == IntentLabel.OUT_OF_SCOPE:
        raise GuardrailError("intent classified as out of scope", ErrorCode.QUERY_OUT_OF_SCOPE)
