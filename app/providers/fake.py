"""Deterministic providers for unit tests. Never call the network."""

from collections.abc import AsyncIterator

from app.providers.base import LLMResponse
from app.providers.embeddings import HashEmbeddingProvider
from app.schemas.common import TokenUsage


class FakeLLMProvider:
    def __init__(self, canned: dict[str, str] | None = None) -> None:
        self.canned = canned or {}
        self.calls: list[list[dict[str, str]]] = []

    async def ping(self) -> bool:
        return True

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        response_format: dict[str, str] | None = None,
    ) -> LLMResponse:
        self.calls.append(messages)
        user_text = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        for needle, answer in self.canned.items():
            if needle in user_text:
                return LLMResponse(content=answer, usage=TokenUsage(total_tokens=8), model="fake")
        # Default structured-ish reply used by tests that only care about plumbing.
        return LLMResponse(
            content='{"label":"faq_policy","confidence":0.9,"rationale":"fake"}',
            usage=TokenUsage(total_tokens=8),
            model="fake",
        )

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        response_format: dict[str, str] | None = None,
    ) -> AsyncIterator[str]:
        response = await self.generate(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        text = response.content or ""
        for index in range(0, len(text), 4):
            yield text[index : index + 4]


class FakeEmbeddingProvider(HashEmbeddingProvider):
    pass


class OfflineLLMProvider(FakeLLMProvider):
    """Marker for a runtime without a configured generation model.

    FakeLLMProvider remains available for tests with canned structured replies.
    Runtime nodes use this marker to avoid presenting its test JSON as an answer.
    """
