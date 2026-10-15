"""Exponential backoff with full jitter.

Retry storms happen when many instances share the same delay schedule.
Full jitter (sleep = random(0, min(cap, base * 2^attempt))) spreads load.

Only retry transient failures: timeouts, 429, 502, 503, 504.
Never retry 400 / 401 / 403 — those will fail the same way again.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.core.exceptions import AppError, LLMProviderError

logger = logging.getLogger(__name__)

T = TypeVar("T")

RETRYABLE_HTTP_STATUS = frozenset({408, 429, 500, 502, 503, 504})
NON_RETRYABLE_HTTP_STATUS = frozenset({400, 401, 403, 404, 422})


def is_retryable_status(status_code: int) -> bool:
    return status_code in RETRYABLE_HTTP_STATUS


async def with_exponential_backoff(
    operation: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 3,
    base_delay_seconds: float = 0.5,
    max_delay_seconds: float = 8.0,
    operation_name: str = "operation",
    trace_id: str | None = None,
) -> T:
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return await operation()
        except AppError as exc:
            last_error = exc
            if not exc.retryable or attempt == max_attempts - 1:
                raise
            delay = _full_jitter_delay(attempt, base_delay_seconds, max_delay_seconds)
            logger.warning(
                "retryable_failure",
                extra={
                    "operation": operation_name,
                    "attempt": attempt + 1,
                    "max_attempts": max_attempts,
                    "delay_seconds": round(delay, 3),
                    "error_code": exc.error_code.value,
                    "trace_id": trace_id,
                },
            )
            await asyncio.sleep(delay)
        except (TimeoutError, ConnectionError, OSError) as exc:
            last_error = exc
            if attempt == max_attempts - 1:
                raise LLMProviderError(f"{operation_name} exhausted retries", timeout=True) from exc
            delay = _full_jitter_delay(attempt, base_delay_seconds, max_delay_seconds)
            logger.warning(
                "retryable_transport_failure",
                extra={
                    "operation": operation_name,
                    "attempt": attempt + 1,
                    "delay_seconds": round(delay, 3),
                    "trace_id": trace_id,
                },
            )
            await asyncio.sleep(delay)
    assert last_error is not None
    raise last_error


def _full_jitter_delay(attempt: int, base: float, cap: float) -> float:
    ceiling = min(cap, base * (2**attempt))
    return random.uniform(0.0, ceiling)
