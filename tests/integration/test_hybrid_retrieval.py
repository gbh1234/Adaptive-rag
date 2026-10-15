import pytest

from app.config.settings import clear_settings_cache, get_settings
from app.providers.embeddings import HashEmbeddingProvider
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.ingest import ingest_to_memory
from app.retrieval.vector import VectorRetriever


@pytest.mark.asyncio
async def test_hybrid_retrieves_return_policy() -> None:
    clear_settings_cache()
    embedder = HashEmbeddingProvider(dim=get_settings().embedding_dim)
    bm25, store, chunks = await ingest_to_memory("knowledge", embedder)
    assert chunks
    retriever = HybridRetriever(bm25, VectorRetriever(store, embedder), rrf_k=60)
    hits = await retriever.retrieve("定制商品能不能七天无理由退货", top_k=5)
    assert hits
    blob = " ".join(hit.content for hit in hits)
    assert "定制" in blob or "无理由" in blob
