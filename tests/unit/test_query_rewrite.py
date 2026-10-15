"""Unit tests for QueryRewriter: happy path plus every LLM-failure fallback."""

from __future__ import annotations

import pytest

from app.core.exceptions import LLMOutputError, LLMProviderError
from app.providers.fake import FakeLLMProvider
from app.retrieval.query_rewrite import QueryRewriter


class _RaisingLLM:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def generate(self, messages, **kwargs):
        raise self._exc


@pytest.mark.asyncio
async def test_rewrite_returns_llm_queries() -> None:
    llm = FakeLLMProvider(canned={"退货": '{"queries": ["退货政策", "七天无理由条件"]}'})
    out = await QueryRewriter(llm).rewrite("退货")
    assert out == ["退货政策", "七天无理由条件"]


@pytest.mark.asyncio
async def test_rewrite_caps_at_three_queries() -> None:
    llm = FakeLLMProvider(canned={"退货": '{"queries": ["a", "b", "c", "d", "e"]}'})
    out = await QueryRewriter(llm).rewrite("退货")
    assert out == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_rewrite_drops_blank_entries() -> None:
    llm = FakeLLMProvider(canned={"退货": '{"queries": ["   ", "有效查询"]}'})
    out = await QueryRewriter(llm).rewrite("退货")
    assert out == ["有效查询"]


@pytest.mark.asyncio
async def test_rewrite_falls_back_when_list_is_empty() -> None:
    llm = FakeLLMProvider(canned={"退货": '{"queries": []}'})
    assert await QueryRewriter(llm).rewrite("退货") == ["退货"]


@pytest.mark.asyncio
async def test_rewrite_falls_back_when_key_missing() -> None:
    # FakeLLMProvider's default reply has no "queries" key at all.
    llm = FakeLLMProvider()
    assert await QueryRewriter(llm).rewrite("退货") == ["退货"]


@pytest.mark.asyncio
async def test_rewrite_falls_back_on_malformed_json() -> None:
    llm = FakeLLMProvider(canned={"退货": "这不是 JSON"})
    assert await QueryRewriter(llm).rewrite("退货") == ["退货"]


@pytest.mark.asyncio
async def test_rewrite_swallows_provider_error() -> None:
    rewriter = QueryRewriter(_RaisingLLM(LLMProviderError("boom")))
    assert await rewriter.rewrite("退货") == ["退货"]


@pytest.mark.asyncio
async def test_rewrite_swallows_output_error() -> None:
    rewriter = QueryRewriter(_RaisingLLM(LLMOutputError("bad json")))
    assert await rewriter.rewrite("退货") == ["退货"]
