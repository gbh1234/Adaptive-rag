"""Prompt-injection detection."""

from __future__ import annotations

import re

from app.core.error_codes import ErrorCode
from app.core.exceptions import GuardrailError

_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.I),
    re.compile(r"忽略(以上|之前|上面)(的)?(指令|提示)", re.I),
    re.compile(r"you\s+are\s+now\s+", re.I),
    re.compile(r"system\s*prompt", re.I),
    re.compile(r"exfiltrat|send\s+all\s+(user\s+)?(data|information)", re.I),
)


def detect_prompt_injection(text: str) -> None:
    """User text is untrusted. Retrieved docs are also untrusted — caller decides.

    We block obvious jailbreaks at the query boundary. Subtle cases are handled
    by isolating retrieved content behind UNTRUSTED_CONTEXT_BANNER.
    """
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            raise GuardrailError(
                "query looks like prompt injection",
                error_code=ErrorCode.PROMPT_INJECTION_BLOCKED,
            )
