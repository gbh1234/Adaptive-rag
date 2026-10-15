"""Unit tests for the short-TTL retrieval cache.

Covers the memory backend, the Redis backend's degrade paths, and the
order-query guard that keeps user-specific results out of the cache.
"""

from __future__ import annotations

import pytest

from app.retrieval import cache as cache_mod
from app.retrieval.cache import (
    MemoryRetrievalCache,
    RedisRetrievalCache,
    RetrievalCache,
    _looks_like_order_query,
    cache_key,
)
from app.schemas.retrieval import RetrievedChunk


def _chunk(chunk_id: str = "c1", content: str = "七天无理由。") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id="return_policy_0",
        title="退货政策",
        content=content,
        score=1.0,
        rank=1,
        source="bm25",
    )


# --- _looks_like_order_query ------------------------------------------------


def test_order_query_detects_order_id() -> None:
    assert _looks_like_order_query("ORD-2024-001 到哪了") is True


def test_order_query_detects_chinese_keyword() -> None:
    assert _looks_like_order_query("我的订单什么时候到") is True


def test_order_query_is_false_for_policy_question() -> None:
    assert _looks_like_order_query("七天无理由怎么算") is False


# --- cache_key --------------------------------------------------------------


def test_cache_key_is_stable_and_prefixed() -> None:
    assert cache_key("退货", 3) == cache_key("退货", 3)
    assert cache_key("退货", 3).startswith("ret:")


def test_cache_key_varies_with_top_k() -> None:
    assert cache_key("退货", 3) != cache_key("退货", 5)


# --- base class -------------------------------------------------------------


@pytest.mark.asyncio
async def test_base_cache_is_a_noop() -> None:
    cache = RetrievalCache()
    assert await cache.get("x", 1) is None
    assert await cache.set("x", 1, [_chunk()]) is None


# --- MemoryRetrievalCache ---------------------------------------------------


@pytest.mark.asyncio
async def test_memory_cache_roundtrip() -> None:
    cache = MemoryRetrievalCache(ttl_seconds=60)
    await cache.set("七天无理由", 3, [_chunk()])
    got = await cache.get("七天无理由", 3)
    assert got is not None
    assert got[0].chunk_id == "c1"


@pytest.mark.asyncio
async def test_memory_cache_miss_returns_none() -> None:
    cache = MemoryRetrievalCache(ttl_seconds=60)
    assert await cache.get("从未写入过", 3) is None


@pytest.mark.asyncio
async def test_memory_cache_never_stores_order_queries() -> None:
    cache = MemoryRetrievalCache(ttl_seconds=60)
    await cache.set("订单 ORD-1 到哪了", 3, [_chunk()])
    assert await cache.get("订单 ORD-1 到哪了", 3) is None


@pytest.mark.asyncio
async def test_memory_cache_expires_after_ttl(monkeypatch) -> None:
    clock = {"now": 1000.0}
    monkeypatch.setattr(cache_mod.time, "monotonic", lambda: clock["now"])
    cache = MemoryRetrievalCache(ttl_seconds=10)
    await cache.set("退货政策", 3, [_chunk()])
    assert await cache.get("退货政策", 3) is not None
    clock["now"] = 1011.0
    assert await cache.get("退货政策", 3) is None


# --- RedisRetrievalCache ----------------------------------------------------


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None):
        self.store[key] = value


class _BrokenRedis:
    async def get(self, key: str):
        raise RuntimeError("redis down")

    async def set(self, key: str, value: str, ex: int | None = None):
        raise RuntimeError("redis down")


@pytest.mark.asyncio
async def test_redis_cache_roundtrip() -> None:
    cache = RedisRetrievalCache(_FakeRedis(), ttl_seconds=60)
    await cache.set("七天无理由", 3, [_chunk()])
    got = await cache.get("七天无理由", 3)
    assert got is not None
    assert got[0].content == "七天无理由。"


@pytest.mark.asyncio
async def test_redis_cache_miss_returns_none() -> None:
    cache = RedisRetrievalCache(_FakeRedis(), ttl_seconds=60)
    assert await cache.get("没有的查询", 3) is None


@pytest.mark.asyncio
async def test_redis_cache_skips_order_queries() -> None:
    redis = _FakeRedis()
    cache = RedisRetrievalCache(redis, ttl_seconds=60)
    await cache.set("订单 ORD-9 到哪了", 3, [_chunk()])
    assert redis.store == {}


@pytest.mark.asyncio
async def test_redis_cache_get_degrades_on_error() -> None:
    cache = RedisRetrievalCache(_BrokenRedis(), ttl_seconds=60)
    assert await cache.get("退货", 3) is None


@pytest.mark.asyncio
async def test_redis_cache_set_swallows_error() -> None:
    cache = RedisRetrievalCache(_BrokenRedis(), ttl_seconds=60)
    await cache.set("退货", 3, [_chunk()])  # must not raise
