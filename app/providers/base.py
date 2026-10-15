"""Provider protocols and shared response types."""

from collections.abc import AsyncIterator
from typing import Protocol

from app.schemas.common import TokenUsage


class ChatMessageDict(dict):
    """OpenAI-compatible chat message: role + content."""


class LLMResponse:
    """A single chat-completion result.

    Attributes:
        content: The assistant message text.
        usage: Token accounting for the call; defaults to an empty breakdown.
        model: Identifier of the model that produced the response.
    """

    __slots__ = ("content", "usage", "model")

    def __init__(self, content: str, usage: TokenUsage | None = None, model: str = "") -> None:
        self.content = content
        self.usage = usage or TokenUsage()
        self.model = model


class LLMProvider(Protocol):
    """Chat-completion backend (DeepSeek in production, a fake in tests)."""

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        response_format: dict[str, str] | None = None,
    ) -> LLMResponse:
        """Return one completion.

        Args:
            messages: OpenAI-style messages, each with ``role`` and ``content``.
            temperature: Sampling temperature; 0.0 keeps output deterministic.
            max_tokens: Upper bound on generated tokens.
            response_format: Optional constraint such as ``{"type": "json_object"}``.

        Returns:
            The completion together with token usage.

        Raises:
            LLMProviderError: If the upstream call fails after retries.
        """
        ...

    async def ping(self) -> bool:
        """Return True when the backend is reachable."""
        ...

    def stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        response_format: dict[str, str] | None = None,
    ) -> AsyncIterator[str]:
        """Yield completion tokens. Implemented by DeepSeek and Fake providers."""
        ...


class EmbeddingProvider(Protocol):
    """Dense-embedding backend used for indexing and query encoding."""

    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts into vectors of length :attr:`dim`."""
        ...

    async def ping(self) -> bool:
        """Return True when the backend is reachable."""
        ...


class RerankProvider(Protocol):
    """Cross-encoder reranking backend over candidate documents."""

    async def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        top_n: int,
    ) -> list[tuple[int, float]]:
        """Return (original_index, relevance_score) sorted by score desc."""
        ...
