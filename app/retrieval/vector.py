"""Vector stores and dense retrieval over embedded chunks."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from dataclasses import dataclass

from app.core.exceptions import RetrievalError
from app.providers.base import EmbeddingProvider
from app.schemas.retrieval import RetrievedChunk

logger = logging.getLogger(__name__)


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))


def stable_point_id(chunk_id: str) -> str:
    """Qdrant point IDs must be UUID/int. Derive from chunk_id so re-ingest is stable."""
    return str(uuid.UUID(hashlib.md5(chunk_id.encode(), usedforsecurity=False).hexdigest()))


@dataclass
class VectorRecord:
    chunk: RetrievedChunk
    embedding: list[float]


class InMemoryVectorStore:
    """Used in tests and when Qdrant is unavailable."""

    def __init__(self) -> None:
        self._records: list[VectorRecord] = []

    def upsert(self, records: list[VectorRecord]) -> None:
        existing = {record.chunk.chunk_id: index for index, record in enumerate(self._records)}
        for record in records:
            if record.chunk.chunk_id in existing:
                self._records[existing[record.chunk.chunk_id]] = record
            else:
                self._records.append(record)

    def search(self, query_vector: list[float], *, top_k: int) -> list[RetrievedChunk]:
        scored: list[tuple[float, VectorRecord]] = [
            (cosine(query_vector, record.embedding), record) for record in self._records
        ]
        scored.sort(key=lambda item: item[0], reverse=True)
        results: list[RetrievedChunk] = []
        for rank, (score, record) in enumerate(scored[:top_k], start=1):
            chunk = record.chunk.model_copy(deep=True)
            chunk.score = float(score)
            chunk.rank = rank
            chunk.source = "vector"
            results.append(chunk)
        return results

    def ping(self) -> bool:
        return True


class QdrantVectorStore:
    def __init__(self, url: str, collection: str, dim: int) -> None:
        self._url = url
        self._collection = collection
        self._dim = dim
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            from qdrant_client import QdrantClient

            self._client = QdrantClient(url=self._url, timeout=5.0)
        return self._client

    def ensure_collection(self) -> None:
        from qdrant_client.models import Distance, VectorParams

        client = self._ensure_client()
        names = [item.name for item in client.get_collections().collections]
        if self._collection not in names:
            client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=self._dim, distance=Distance.COSINE),
            )

    def upsert(self, records: list[VectorRecord]) -> None:
        from qdrant_client.models import PointStruct

        client = self._ensure_client()
        self.ensure_collection()
        points = [
            PointStruct(
                id=stable_point_id(record.chunk.chunk_id),
                vector=record.embedding,
                payload={
                    "chunk_id": record.chunk.chunk_id,
                    "document_id": record.chunk.document_id,
                    "title": record.chunk.title,
                    "content": record.chunk.content,
                    "section": record.chunk.section,
                    "chunk_index": record.chunk.chunk_index,
                    "policy_version": record.chunk.policy_version,
                    "source": record.chunk.metadata.get("source", "knowledge"),
                },
            )
            for record in records
        ]
        if points:
            client.upsert(collection_name=self._collection, points=points)

    def ping(self) -> bool:
        try:
            self._ensure_client().get_collections()
            return True
        except Exception:
            return False

    def search(self, query_vector: list[float], *, top_k: int) -> list[RetrievedChunk]:
        try:
            client = self._ensure_client()
            hits = client.search(
                collection_name=self._collection,
                query_vector=query_vector,
                limit=top_k,
                with_payload=True,
            )
        except Exception as exc:
            raise RetrievalError("qdrant search failed") from exc
        results: list[RetrievedChunk] = []
        for rank, hit in enumerate(hits, start=1):
            payload = hit.payload or {}
            results.append(
                RetrievedChunk(
                    chunk_id=str(payload.get("chunk_id", hit.id)),
                    document_id=str(payload.get("document_id", "")),
                    title=str(payload.get("title", "")),
                    content=str(payload.get("content", "")),
                    score=float(hit.score),
                    rank=rank,
                    source="vector",
                    section=payload.get("section"),
                    chunk_index=int(payload.get("chunk_index") or 0),
                    policy_version=str(payload.get("policy_version") or "v1"),
                    metadata={"source": str(payload.get("source", "qdrant"))},
                )
            )
        return results


class VectorRetriever:
    def __init__(
        self, store: InMemoryVectorStore | QdrantVectorStore, embedder: EmbeddingProvider
    ) -> None:
        self.store = store
        self.embedder = embedder

    async def search(self, query: str, *, top_k: int) -> list[RetrievedChunk]:
        vectors = await self.embedder.embed([query])
        if not vectors:
            return []
        # Qdrant client is sync; do not block the event loop.
        return await asyncio.to_thread(self.store.search, vectors[0], top_k=top_k)

    async def ping(self) -> bool:
        return await asyncio.to_thread(self.store.ping)


def build_records(
    chunks: list[RetrievedChunk],
    embeddings: list[list[float]],
) -> list[VectorRecord]:
    if len(chunks) != len(embeddings):
        raise ValueError("chunk / embedding length mismatch")
    return [
        VectorRecord(chunk=chunk, embedding=embedding)
        for chunk, embedding in zip(chunks, embeddings, strict=False)
    ]
