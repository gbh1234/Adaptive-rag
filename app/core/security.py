"""Log redaction and PII masking. Never log secrets or raw identifiers."""

from __future__ import annotations

import re

from app.core.constants import PII_MASK

_SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "access_token",
        "refresh_token",
        "password",
        "cookie",
        "secret",
    }
)

_PHONE = re.compile(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)")
_ID_CARD = re.compile(r"\b(\d{6})\d{8,10}(\d{2}[\dXx])\b")
_BANK_CARD = re.compile(r"\b(\d{4})\d{8,11}(\d{4})\b")
_ORDER_ID = re.compile(r"\b(ORD)[-_]?(\d{4})\d+(\d{2})\b", re.IGNORECASE)


def redact_mapping(payload: dict[str, object]) -> dict[str, object]:
    redacted: dict[str, object] = {}
    for key, value in payload.items():
        if key.lower() in _SECRET_KEYS:
            redacted[key] = PII_MASK
        elif isinstance(value, str):
            redacted[key] = mask_pii(value)
        elif isinstance(value, dict):
            redacted[key] = redact_mapping(value)  # type: ignore[arg-type]
        else:
            redacted[key] = value
    return redacted


def mask_pii(text: str) -> str:
    text = _PHONE.sub(rf"\1{PII_MASK}\2", text)
    text = _ID_CARD.sub(rf"\1{PII_MASK}\2", text)
    text = _BANK_CARD.sub(rf"\1{PII_MASK}\2", text)
    text = _ORDER_ID.sub(rf"\1{PII_MASK}\3", text)
    return text
