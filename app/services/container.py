"""Dependency-injection container and runtime composition."""

from __future__ import annotations

import logging

from app.config.settings import Settings
from app.infra.rate_limit import InMemoryRateLimiter, RedisRateLimiter
from app.infra.redis_client import connect_redis
from app.mcp.adapter import merge_mcp_tools
from app.mcp.runtime import LOCAL_CATALOG
from app.providers.base import LLMProvider
from app.providers.deepseek import DeepSeekProvider
from app.providers.embeddings import build_embedding_provider
from app.providers.fake import OfflineLLMProvider
from app.providers.reranker import CrossEncoderRerankProvider
from app.repositories.db import create_engine, create_session_factory, init_schema
from app.retrieval.cache import MemoryRetrievalCache, RedisRetrievalCache
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.ingest import ingest_knowledge
from app.retrieval.reranker import DocumentReranker
from app.retrieval.vector import VectorRetriever
from app.services.chat_service import ChatService
from app.services.seed import seed_demo_data
from app.tools.factory import build_tool_registry

logger = logging.getLogger(__name__)


class AppContainer:
    def __init__(
        self,
        settings: Settings,
        llm: LLMProvider,
        chat_service: ChatService,
        engine,
        session_factory,
        retriever: HybridRetriever,
        redis=None,
        vector_store=None,
    ) -> None:
        self.settings = settings
        self.llm = llm
        self.chat_service = chat_service
        self.engine = engine
        self.session_factory = session_factory
        self.retriever = retriever
        self.redis = redis
        self.vector_store = vector_store

    async def aclose(self) -> None:
        closer = getattr(self.llm, "aclose", None)
        if closer:
            await closer()
        if self.redis is not None:
            closer = getattr(self.redis, "aclose", None)
            if closer:
                await closer()
        await self.engine.dispose()


async def build_infrastructure(settings: Settings):
    """Create the database session factory and optional Redis connection."""
    engine = create_engine(settings)
    await init_schema(engine)
    session_factory = create_session_factory(engine)
    redis = await connect_redis(settings)
    return engine, session_factory, redis


async def build_retrieval(settings: Settings, redis):
    """Build the knowledge ingestion and hybrid retrieval components."""
    embedder = build_embedding_provider(settings)
    cache = (
        RedisRetrievalCache(redis, ttl_seconds=settings.retrieval_cache_ttl_seconds)
        if redis is not None
        else MemoryRetrievalCache(ttl_seconds=settings.retrieval_cache_ttl_seconds)
    )
    bm25, store, _ = await ingest_knowledge(
        settings.knowledge_dir,
        embedder,
        settings=settings,
        qdrant_url=settings.qdrant_url,
        qdrant_collection=settings.qdrant_collection,
        embedding_dim=getattr(embedder, "dim", settings.embedding_dim),
    )
    retriever = HybridRetriever(
        bm25, VectorRetriever(store, embedder), rrf_k=settings.rrf_k, cache=cache
    )
    reranker = DocumentReranker(CrossEncoderRerankProvider(settings))
    return retriever, reranker, store


async def build_container(settings: Settings, seed: bool = False) -> AppContainer:
    """Compose runtime services from independently testable infrastructure builders."""
    llm: LLMProvider = (
        DeepSeekProvider(settings) if settings.llm_configured else OfflineLLMProvider()
    )
    engine, session_factory, redis = await build_infrastructure(settings)
    rate_limiter = (
        RedisRateLimiter(redis, limit=settings.rate_limit_per_minute)
        if redis is not None
        else InMemoryRateLimiter(limit=settings.rate_limit_per_minute)
    )
    retriever, reranker, store = await build_retrieval(settings, redis)
    registry = build_tool_registry(retriever)
    if settings.mcp_enabled:
        specs = list(LOCAL_CATALOG)
        if settings.mcp_remote_url:
            specs.append(
                {
                    "name": "mcp_remote_echo",
                    "description": "Remote MCP tool via HTTP (same Function Calling schema)",
                    "transport": "http",
                    "endpoint": settings.mcp_remote_url.rstrip("/") + "/mcp/call",
                }
            )
        merge_mcp_tools(registry, specs)
    chat_service = ChatService(
        settings=settings,
        llm=llm,
        retriever=retriever,
        reranker=reranker,
        session_factory=session_factory,
        rate_limiter=rate_limiter,
        registry=registry,
    )
    if seed:
        async with session_factory() as session:
            await seed_demo_data(session)
            await session.commit()
    return AppContainer(
        settings=settings,
        llm=llm,
        chat_service=chat_service,
        engine=engine,
        session_factory=session_factory,
        retriever=retriever,
        redis=redis,
        vector_store=store,
    )
