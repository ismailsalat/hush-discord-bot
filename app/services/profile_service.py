"""Public anonymous profiles.

A profile belongs to an *alias*, not to a person. A rotated alias keeps its old
profile intact and the new alias starts empty - which is what makes rotation a
real privacy reset rather than a cosmetic rename.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AliasNotFoundError
from app.database.repositories import (
    AliasRepository,
    ConfessionRepository,
    FollowRepository,
    GuildRepository,
)
from app.security.identifiers import format_alias
from app.services.dto import ProfileView
from app.utils.text import one_line


class ProfileService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.aliases = AliasRepository(session)
        self.confessions = ConfessionRepository(session)
        self.follows = FollowRepository(session)
        self.guilds = GuildRepository(session)

    async def build(self, alias_id: str, *, recent_limit: int = 4) -> ProfileView:
        alias = await self.aliases.get(alias_id)
        if alias is None:
            raise AliasNotFoundError()

        settings = await self.guilds.get_settings(alias.guild_id)
        scale_max = settings.rating_scale_max if settings else 5

        average, rating_count = await self.confessions.alias_rating_summary(alias_id)
        most_rated = await self.confessions.most_rated_for_alias(alias_id)
        recent = await self.confessions.list_for_alias(alias_id, limit=recent_limit)

        return ProfileView(
            alias_id=alias.id,
            alias_display=format_alias(alias.public_alias),
            guild_id=alias.guild_id,
            is_current=alias.is_current,
            confession_count=await self.confessions.count_for_alias(alias_id),
            average_rating=average,
            rating_count=rating_count,
            follower_count=await self.follows.count_for_alias(alias_id),
            most_rated_number=most_rated[0].public_number if most_rated else None,
            most_rated_rating_count=most_rated[1] if most_rated else 0,
            recent=[(item.public_number, one_line(item.content, 44)) for item in recent],
            scale_max=scale_max,
        )

    async def build_for_user(self, internal_user_id: str, guild_id: int) -> ProfileView:
        """The caller's own current profile."""
        alias = await self.aliases.get_current(internal_user_id, guild_id)
        if alias is None:
            raise AliasNotFoundError()
        return await self.build(alias.id)

    async def list_all_confessions(self, alias_id: str, limit: int = 50) -> list[tuple[int, str]]:
        confessions = await self.confessions.list_for_alias(alias_id, limit=limit)
        return [(item.public_number, one_line(item.content, 56)) for item in confessions]
