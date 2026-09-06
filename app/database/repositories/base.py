"""Shared repository base."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository:
    """Holds the session. Repositories never commit - the session scope does."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def flush(self) -> None:
        await self.session.flush()
