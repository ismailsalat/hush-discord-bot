"""Ratings: a single overall reaction score per confession."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.core.exceptions import FeatureDisabledError, InvalidRatingError
from app.database.repositories import ConfessionRepository, GuildRepository, RatingRepository


class RatingService:
    """A rating means "how strongly did you react to this", nothing more.

    One button, one scale - not a morality or funniness score.
    """

    def __init__(self, session: AsyncSession, settings: Settings):
        self.session = session
        self.settings = settings
        self.ratings = RatingRepository(session)
        self.confessions = ConfessionRepository(session)
        self.guilds = GuildRepository(session)

    async def scale(self, guild_id: int) -> tuple[int, int]:
        settings = await self.guilds.get_settings(guild_id)
        maximum = settings.rating_scale_max if settings else self.settings.rating_scale_max
        return self.settings.rating_scale_min, maximum

    async def get_existing_value(self, confession_id: str, voter_internal_user_id: str) -> int | None:
        rating = await self.ratings.get_for_voter(confession_id, voter_internal_user_id)
        return rating.value if rating else None

    async def rate(
        self, *, confession_id: str, guild_id: int, voter_internal_user_id: str, value: int
    ) -> tuple[int, bool]:
        """Create or change a rating. Returns ``(value, was_created)``."""
        settings = await self.guilds.get_settings(guild_id)
        if settings is not None and not settings.ratings_enabled:
            raise FeatureDisabledError(user_message="Ratings are turned off in this server.")

        low, high = await self.scale(guild_id)
        if not low <= value <= high:
            raise InvalidRatingError(low, high)

        _rating, created = await self.ratings.upsert(confession_id, voter_internal_user_id, value)
        return value, created

    async def summary(self, confession_id: str) -> tuple[float | None, int]:
        return await self.confessions.rating_summary(confession_id)
