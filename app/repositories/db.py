"""Async engine, session factory and schema initialisation."""

from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.config.settings import Settings
from app.repositories.models import Base


def create_engine(settings: Settings) -> AsyncEngine:
    connect_args: dict[str, object] = {}
    kwargs: dict[str, object] = {
        "echo": False,
        "pool_pre_ping": True,
        "connect_args": connect_args,
    }
    if settings.use_sqlite:
        Path("data/local").mkdir(parents=True, exist_ok=True)
        connect_args["check_same_thread"] = False
        if ":memory:" in settings.database_url:
            kwargs["poolclass"] = StaticPool
    else:
        kwargs["pool_size"] = settings.db_pool_size
        kwargs["max_overflow"] = settings.db_max_overflow
        kwargs["pool_timeout"] = settings.db_pool_timeout
        kwargs["pool_recycle"] = 1800
    return create_async_engine(settings.database_url, **kwargs)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        yield session
