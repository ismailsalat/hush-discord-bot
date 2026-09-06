"""Ratings: one row per voter per confession, updated in place."""

from __future__ import annotations

from sqlalchemy import func, select

from app.database.models import Confession, Rating
from app.database.repositories.base import BaseRepository


class RatingRepository(BaseRepository):
    async def get_for_voter(self, confession_id: str, voter_internal_user_id: str) -> Rating | None:
        result = await self.session.execute(
            select(Rating).where(
                Rating.confession_id == confession_id,
                Rating.voter_internal_user_id == voter_internal_user_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self, confession_id: str, voter_internal_user_id: str, value: int
    ) -> tuple[Rating, bool]:
        """Create or update a rating. Returns ``(rating, was_created)``.

        Changing a rating must never add a second row - the unique constraint
        enforces that, and this method is the only write path.
        """
        existing = await self.get_for_voter(confession_id, voter_internal_user_id)
        if existing is not None:
            existing.value = value
            await self.session.flush()
            return existing, False

        rating = Rating(
            confession_id=confession_id,
            voter_internal_user_id=voter_internal_user_id,
            value=value,
        )
        self.session.add(rating)
        await self.session.flush()
        return rating, True

    async def list_for_confession(self, confession_id: str) -> list[Rating]:
        result = await self.session.execute(
            select(Rating).where(Rating.confession_id == confession_id)
        )
        return list(result.scalars().all())

    async def list_by_voter(self, voter_internal_user_id: str) -> list[Rating]:
        result = await self.session.execute(
            select(Rating).where(Rating.voter_internal_user_id == voter_internal_user_id)
        )
        return list(result.scalars().all())

    async def highest_rated(
        self, guild_id: int, *, minimum_ratings: int = 3, limit: int = 5
    ) -> list[tuple[Confession, float, int]]:
        """Hall of Fame: best average, gated by a minimum number of votes."""
        result = await self.session.execute(
            select(Confession, func.avg(Rating.value), func.count(Rating.id))
            .join(Rating, Rating.confession_id == Confession.id)
            .where(Confession.guild_id == guild_id, Confession.is_deleted.is_(False))
            .group_by(Confession.id)
            .having(func.count(Rating.id) >= minimum_ratings)
            .order_by(func.avg(Rating.value).desc(), func.count(Rating.id).desc())
            .limit(limit)
        )
        return [(row[0], float(row[1]), int(row[2])) for row in result.all()]

    async def most_rated(self, guild_id: int, *, limit: int = 5) -> list[tuple[Confession, int]]:
        result = await self.session.execute(
            select(Confession, func.count(Rating.id))
            .join(Rating, Rating.confession_id == Confession.id)
            .where(Confession.guild_id == guild_id, Confession.is_deleted.is_(False))
            .group_by(Confession.id)
            .order_by(func.count(Rating.id).desc())
            .limit(limit)
        )
        return [(row[0], int(row[1])) for row in result.all()]

    async def most_discussed(self, guild_id: int, *, limit: int = 5) -> list[Confession]:
        result = await self.session.execute(
            select(Confession)
            .where(
                Confession.guild_id == guild_id,
                Confession.is_deleted.is_(False),
                Confession.reply_count > 0,
            )
            .order_by(Confession.reply_count.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
