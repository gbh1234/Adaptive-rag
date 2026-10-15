import pytest

from app.core.exceptions import LLMProviderError
from app.core.retry import with_exponential_backoff
from app.infra.rate_limit import InMemoryRateLimiter
from app.repositories.order_repository import escape_like


@pytest.mark.asyncio
async def test_retries_retryable_then_succeeds() -> None:
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise LLMProviderError("tmp", timeout=True)
        return "ok"

    result = await with_exponential_backoff(
        flaky, max_attempts=4, base_delay_seconds=0.01, max_delay_seconds=0.02
    )
    assert result == "ok"
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_does_not_retry_auth_errors() -> None:
    calls = {"n": 0}

    async def unauthorized():
        calls["n"] += 1
        raise LLMProviderError("DeepSeek HTTP 401", retryable=False)

    with pytest.raises(LLMProviderError):
        await with_exponential_backoff(unauthorized, max_attempts=3, base_delay_seconds=0.01)
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_memory_rate_limiter_blocks() -> None:
    limiter = InMemoryRateLimiter(limit=2, window_seconds=60)
    assert await limiter.allow("u1")
    assert await limiter.allow("u1")
    assert not await limiter.allow("u1")
    assert await limiter.allow("u2")


def test_like_escape_does_not_treat_percent_as_wildcard() -> None:
    assert escape_like("100%_off") == "100\\%\\_off"
