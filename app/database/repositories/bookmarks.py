"""Private bookmark storage."""

from __future__ import annotations

from sqlalchemy import delete, func, select

from app.core.constants import ConfessionStatus
from app.database.models import Bookmark, Confession
from app.database.repositories.base import BaseRepository


class BookmarkRepository(BaseRepository):
    async def get(self, internal_user_id: str, confession_id: str) -> Bookmark | None:
        result = await self.session.execute(
            select(Bookmark).where(
                Bookmark.internal_user_id == internal_user_id,
                Bookmark.confession_id == confession_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, internal_user_id: str, confession_id: str) -> Bookmark:
        bookmark = Bookmark(internal_user_id=internal_user_id, confession_id=confession_id)
        self.session.add(bookmark)
        await self.session.flush()
        return bookmark

    async def delete(self, internal_user_id: str, confession_id: str) -> bool:
        result = await self.session.execute(
            delete(Bookmark).where(
                Bookmark.internal_user_id == internal_user_id,
                Bookmark.confession_id == confession_id,
            )
        )
        return bool(result.rowcount)

    async def list_for_user(
        self, internal_user_id: str, guild_id: int | None = None
    ) -> list[tuple[Bookmark, Confession]]:
        """Saved confessions, skipping any that have since been removed."""
        query = (
            select(Bookmark, Confession)
            .join(Confession, Confession.id == Bookmark.confession_id)
            .where(
                Bookmark.internal_user_id == internal_user_id,
                Confession.is_deleted.is_(False),
                Confession.status == ConfessionStatus.POSTED,
            )
        )
        if guild_id is not None:
            query = query.where(Confession.guild_id == guild_id)
        result = await self.session.execute(query.order_by(Bookmark.created_at.desc()))
        return [(row[0], row[1]) for row in result.all()]

    async def list_raw_for_user(self, internal_user_id: str) -> list[Bookmark]:
        result = await self.session.execute(
            select(Bookmark).where(Bookmark.internal_user_id == internal_user_id)
        )
        return list(result.scalars().all())

    async def count_for_user(self, internal_user_id: str) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Bookmark).where(
                Bookmark.internal_user_id == internal_user_id
            )
        )
        return int(result.scalar_one())
