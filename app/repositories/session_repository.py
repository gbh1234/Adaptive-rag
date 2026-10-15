"""Conversation session and message persistence."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utcnow
from app.repositories.models import MessageRow, SessionRow
from app.schemas.chat import ChatMessage


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create(self, session_id: str, user_id: str) -> SessionRow:
        row = await self._session.get(SessionRow, session_id)
        if row is None:
            row = SessionRow(session_id=session_id, user_id=user_id)
            self._session.add(row)
            await self._session.flush()
        return row

    async def recent_messages(self, session_id: str, *, limit: int = 20) -> list[ChatMessage]:
        result = await self._session.execute(
            select(MessageRow)
            .where(MessageRow.session_id == session_id)
            .order_by(MessageRow.id.desc())
            .limit(limit)
        )
        rows = list(reversed(result.scalars().all()))
        return [ChatMessage(role=row.role, content=row.content) for row in rows]  # type: ignore[arg-type]

    async def append_message(self, session_id: str, role: str, content: str) -> None:
        self._session.add(MessageRow(session_id=session_id, role=role, content=content))
        row = await self._session.get(SessionRow, session_id)
        if row is not None:
            row.updated_at = utcnow()

    async def save_summary(self, session_id: str, summary: str) -> None:
        row = await self._session.get(SessionRow, session_id)
        if row is not None:
            row.summary = summary
            row.updated_at = utcnow()
