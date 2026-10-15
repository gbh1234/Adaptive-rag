"""Unit tests for the Self-RAG retrieve → grade → hop loop.

The loop is driven with stubs so no real retrieval, rerank or LLM call happens.
"""

from __future__ import annotations

import pytest

from app.config.settings import Settings
from app.core.exceptions import LLMProviderError
from app.providers.fake import FakeLLMProvider
from app.retrieval.self_rag import SelfRAGLoop
from app.schemas.retrieval import RetrievedChunk

_SUFFICIENT = '{"relevant": true, "sufficient": true, "missing_aspect": "", "rationale": "ok"}'
_NOT_SUFFICIENT = (
    '{"relevant": true, "sufficient": false, "missing_aspect": "赔付", "rationale": "partial"}'
)


def _chunk(chunk_id: str, content: str = "政策正文") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=f"policy_{chunk_id}",
        title="政策",
        content=content,
        score=1.0,
        rank=1,
        source="bm25",
    )


class _StubRetriever:
    def __init__(self, per_query: dict[str, list[RetrievedChunk]]) -> None:
        self._per_query = per_query
        self.calls: list[str] = []

    async def retrieve(self, query: str, *, top_k: int) -> list[RetrievedChunk]:
        self.calls.append(query)
        return list(self._per_query.get(query, []))


class _StubReranker:
    async def rerank(self, query, chunks, *, top_n):
        return list(chunks)[:top_n]


class _PassthroughReranker:
    """Ignores top_n so the accumulator grows past it — used to test the final cap."""

    async def rerank(self, query, chunks, *, top_n):
        return list(chunks)


class _StubRewriter:
    def __init__(self) -> None:
        self.calls = 0

    async def rewrite(self, query: str, *, missing_aspect: str = "") -> list[str]:
        self.calls += 1
        return [query]


class _RaisingLLM:
    async def generate(self, messages, **kwargs):
        raise LLMProviderError("grading llm down")


def _loop(*, llm, retriever, hops: int = 3, rerank_top_n: int = 5) -> SelfRAGLoop:
    return SelfRAGLoop(
        retriever=retriever,
        reranker=_StubReranker(),
        rewriter=_StubRewriter(),
        llm=llm,
        settings=Settings(max_retrieval_hops=hops, rerank_top_n=rerank_top_n),
    )


@pytest.mark.asyncio
async def test_loop_stops_when_first_grade_is_sufficient() -> None:
    llm = FakeLLMProvider(canned={"": _SUFFICIENT})
    retriever = _StubRetriever({"退货": [_chunk("c1")]})
    loop = _loop(llm=llm, retriever=retriever)

    chunks = await loop.retrieve("退货", top_k=3)

    assert [c.chunk_id for c in chunks] == ["c1"]
    assert len(retriever.calls) == 1
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_loop_hops_again_and_dedupes_chunks() -> None:
    llm = FakeLLMProvider(canned={"": _NOT_SUFFICIENT})
    retriever = _StubRetriever({"退货": [_chunk("c1"), _chunk("c2")]})
    loop = _loop(llm=llm, retriever=retriever, hops=2)

    chunks = await loop.retrieve("退货", top_k=3)

    # Same chunks come back on both hops, so the accumulator must dedupe.
    assert [c.chunk_id for c in chunks] == ["c1", "c2"]
    assert len(retriever.calls) == 2
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_loop_respects_max_hops() -> None:
    llm = FakeLLMProvider(canned={"": _NOT_SUFFICIENT})
    retriever = _StubRetriever({"退货": [_chunk("c1")]})
    loop = _loop(llm=llm, retriever=retriever, hops=1)

    await loop.retrieve("退货", top_k=3)

    assert len(retriever.calls) == 1


@pytest.mark.asyncio
async def test_loop_truncates_to_twice_rerank_top_n() -> None:
    llm = FakeLLMProvider(canned={"": _SUFFICIENT})
    chunks = [_chunk(f"c{i}") for i in range(10)]
    retriever = _StubRetriever({"退货": chunks})
    loop = SelfRAGLoop(
        retriever=retriever,
        reranker=_PassthroughReranker(),
        rewriter=_StubRewriter(),
        llm=llm,
        settings=Settings(max_retrieval_hops=1, rerank_top_n=2),
    )

    got = await loop.retrieve("退货", top_k=10)

    assert len(got) == 4  # 10 accumulated, capped at rerank_top_n * 2


@pytest.mark.asyncio
async def test_loop_degrades_when_grading_llm_fails() -> None:
    retriever = _StubRetriever({"退货": [_chunk("c1")]})
    loop = _loop(llm=_RaisingLLM(), retriever=retriever, hops=1)

    chunks = await loop.retrieve("退货", top_k=3)

    # Fallback treats "we have chunks" as sufficient, so the hop stops.
    assert [c.chunk_id for c in chunks] == ["c1"]


@pytest.mark.asyncio
async def test_loop_returns_empty_when_nothing_retrieved_and_grading_fails() -> None:
    retriever = _StubRetriever({})  # every query yields nothing
    loop = _loop(llm=_RaisingLLM(), retriever=retriever, hops=1)

    assert await loop.retrieve("退货", top_k=3) == []
