"""Idempotency-key storage for write operations."""

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.error_codes import ErrorCode
from app.core.exceptions import AppError
from app.repositories.models import IdempotencyRow


class IdempotencyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_if_matches(self, key: str, fingerprint: str) -> dict | None:
        row = await self._session.get(IdempotencyRow, key)
        if row is None:
            return None
        if row.fingerprint != fingerprint:
            raise AppError(
                "idempotency key reused with different payload",
                error_code=ErrorCode.IDEMPOTENCY_CONFLICT,
                http_status=409,
            )
        return json.loads(row.response_json)

    async def put(self, key: str, fingerprint: str, response: dict) -> None:
        existing = await self._session.get(IdempotencyRow, key)
        if existing is not None:
            if existing.fingerprint != fingerprint:
                raise AppError(
                    "idempotency key reused with different payload",
                    error_code=ErrorCode.IDEMPOTENCY_CONFLICT,
                    http_status=409,
                )
            return
        self._session.add(
            IdempotencyRow(
                key=key,
                fingerprint=fingerprint,
                response_json=json.dumps(response, ensure_ascii=False),
            )
        )
