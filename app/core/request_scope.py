"""Request-scoped resources via contextvars.

LangGraph is compiled once at process start. Tools still need the current
SQLAlchemy session; storing the session on the compiled graph would leak
connections across requests. Contextvars keep the binding request-local
and async-safe.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar, Token

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_db_session: ContextVar[AsyncSession | None] = ContextVar("db_session", default=None)


def get_db_session() -> AsyncSession:
    session = _db_session.get()
    if session is None:
        raise RuntimeError("no request-scoped database session")
    return session


@asynccontextmanager
async def request_session(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        token: Token = _db_session.set(session)
        try:
            yield session
        finally:
            _db_session.reset(token)
