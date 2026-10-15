"""Query rewriting for multi-hop and ambiguous queries."""

from __future__ import annotations

from app.core.exceptions import LLMOutputError, LLMProviderError
from app.prompts.query_rewrite import REWRITE_SYSTEM, REWRITE_USER
from app.providers.base import LLMProvider
from app.providers.fake import OfflineLLMProvider
from app.providers.json_parser import extract_json_object


class QueryRewriter:
    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def rewrite(self, query: str, *, missing_aspect: str = "") -> list[str]:
        if isinstance(self._llm, OfflineLLMProvider):
            return [query]
        try:
            response = await self._llm.generate(
                [
                    {"role": "system", "content": REWRITE_SYSTEM},
                    {
                        "role": "user",
                        "content": REWRITE_USER.format(
                            query=query, missing_aspect=missing_aspect or "none"
                        ),
                    },
                ],
                temperature=0.0,
                max_tokens=256,
                response_format={"type": "json_object"},
            )
            payload = extract_json_object(response.content)
            queries = payload.get("queries") or []
            cleaned = [str(item).strip() for item in queries if str(item).strip()]
            return cleaned[:3] or [query]
        except (LLMProviderError, LLMOutputError):
            return [query]
