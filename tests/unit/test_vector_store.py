"""Unit tests for in-memory vector search and record building."""

from __future__ import annotations

import pytest

from app.retrieval.vector import (
    InMemoryVectorStore,
    VectorRecord,
    VectorRetriever,
    build_records,
    cosine,
    stable_point_id,
)
from app.schemas.retrieval import RetrievedChunk


def _chunk(chunk_id: str, content: str = "正文") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id="policy_0",
        title="政策",
        content=content,
        score=0.0,
        source="bm25",
    )


class _FixedEmbedder:
    """Always returns the same vector so cosine scores stay deterministic."""

    def __init__(self, vector: list[float]) -> None:
        self._vector = vector

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(self._vector) for _ in texts]


class _EmptyEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return []


# --- cosine -----------------------------------------------------------------


def test_cosine_is_a_dot_product() -> None:
    assert cosine([1.0, 2.0, 3.0], [4.0, 5.0, 6.0]) == 32.0


def test_cosine_ignores_trailing_length_mismatch() -> None:
    assert cosine([1.0, 1.0], [1.0]) == 1.0


# --- stable_point_id --------------------------------------------------------


def test_stable_point_id_is_deterministic_uuid() -> None:
    first = stable_point_id("return_policy_0")
    assert first == stable_point_id("return_policy_0")
    assert first != stable_point_id("return_policy_1")
    assert len(first) == 36  # canonical UUID string


# --- InMemoryVectorStore ----------------------------------------------------


def test_in_memory_search_orders_by_score() -> None:
    store = InMemoryVectorStore()
    store.upsert(
        [
            VectorRecord(chunk=_chunk("c1"), embedding=[1.0, 0.0]),
            VectorRecord(chunk=_chunk("c2"), embedding=[0.0, 1.0]),
        ]
    )
    hits = store.search([1.0, 0.0], top_k=2)

    assert [h.chunk_id for h in hits] == ["c1", "c2"]
    assert hits[0].rank == 1
    assert hits[0].source == "vector"
    assert hits[0].score == 1.0


def test_in_memory_upsert_replaces_same_chunk_id() -> None:
    store = InMemoryVectorStore()
    store.upsert([VectorRecord(chunk=_chunk("c1", "旧"), embedding=[1.0])])
    store.upsert([VectorRecord(chunk=_chunk("c1", "新"), embedding=[1.0])])

    hits = store.search([1.0], top_k=5)

    assert len(hits) == 1
    assert hits[0].content == "新"


def test_in_memory_search_respects_top_k() -> None:
    store = InMemoryVectorStore()
    store.upsert([VectorRecord(chunk=_chunk(f"c{i}"), embedding=[float(i)]) for i in range(5)])

    assert len(store.search([1.0], top_k=2)) == 2


def test_in_memory_search_does_not_mutate_stored_chunk() -> None:
    store = InMemoryVectorStore()
    original = _chunk("c1")
    store.upsert([VectorRecord(chunk=original, embedding=[1.0])])

    store.search([1.0], top_k=1)

    assert original.rank is None
    assert original.source == "bm25"


def test_in_memory_ping_is_true() -> None:
    assert InMemoryVectorStore().ping() is True


# --- build_records ----------------------------------------------------------


def test_build_records_pairs_chunks_with_embeddings() -> None:
    records = build_records([_chunk("c1")], [[0.1, 0.2]])
    assert records[0].chunk.chunk_id == "c1"
    assert records[0].embedding == [0.1, 0.2]


def test_build_records_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError, match="length mismatch"):
        build_records([_chunk("c1")], [])


# --- VectorRetriever --------------------------------------------------------


@pytest.mark.asyncio
async def test_vector_retriever_searches_with_embedded_query() -> None:
    store = InMemoryVectorStore()
    store.upsert([VectorRecord(chunk=_chunk("c1"), embedding=[1.0, 0.0])])
    retriever = VectorRetriever(store, _FixedEmbedder([1.0, 0.0]))

    hits = await retriever.search("退货", top_k=1)

    assert len(hits) == 1
    assert hits[0].chunk_id == "c1"
    assert hits[0].score == 1.0


@pytest.mark.asyncio
async def test_vector_retriever_returns_empty_without_embedding() -> None:
    retriever = VectorRetriever(InMemoryVectorStore(), _EmptyEmbedder())
    assert await retriever.search("退货", top_k=1) == []


@pytest.mark.asyncio
async def test_vector_retriever_ping_delegates_to_store() -> None:
    retriever = VectorRetriever(InMemoryVectorStore(), _FixedEmbedder([1.0]))
    assert await retriever.ping() is True
