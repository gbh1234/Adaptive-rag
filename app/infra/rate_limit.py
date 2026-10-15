"""Per-user rate limiting.

Fail-open if Redis errors: availability over strict throttling.
Auth stays fail-closed elsewhere.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque

logger = logging.getLogger(__name__)


class RateLimiter:
    async def allow(self, key: str) -> bool:
        raise NotImplementedError


class InMemoryRateLimiter(RateLimiter):
    def __init__(self, *, limit: int, window_seconds: int = 60) -> None:
        self._limit = limit
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def allow(self, key: str) -> bool:
        now = time.monotonic()
        async with self._lock:
            bucket = self._hits[key]
            cutoff = now - self._window
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self._limit:
                return False
            bucket.append(now)
            return True


class RedisRateLimiter(RateLimiter):
    """Sliding window via sorted set. Falls back to allow-on-error."""

    def __init__(self, redis, *, limit: int, window_seconds: int = 60) -> None:
        self._redis = redis
        self._limit = limit
        self._window = window_seconds

    async def allow(self, key: str) -> bool:
        now = time.time()
        window_key = f"rl:{key}"
        try:
            pipe = self._redis.pipeline()
            pipe.zremrangebyscore(window_key, 0, now - self._window)
            pipe.zcard(window_key)
            pipe.zadd(window_key, {f"{now}": now})
            pipe.expire(window_key, self._window)
            results = await pipe.execute()
            count = int(results[1])
            return count < self._limit
        except Exception:
            logger.warning("rate_limiter_redis_failed_open", extra={"key": key})
            return True
