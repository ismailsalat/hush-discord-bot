"""Following an anonymous alias.

Follows attach to an alias, never a person. When someone rotates, the new alias
starts with zero followers - that is intended, not a bug.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AliasNotFoundError,
    AlreadyFollowingError,
    CannotFollowSelfError,
    FeatureDisabledError,
    NotFollowingError,
)
from app.database.models import AnonAlias, Follow
from app.database.repositories import AliasRepository, FollowRepository, GuildRepository


class FollowService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.follows = FollowRepository(session)
        self.aliases = AliasRepository(session)
        self.guilds = GuildRepository(session)

    async def _check_enabled(self, guild_id: int) -> None:
        settings = await self.guilds.get_settings(guild_id)
        if settings is not None and not settings.followers_enabled:
            raise FeatureDisabledError(user_message="Following is turned off in this server.")

    async def follow(self, *, follower_internal_user_id: str, alias_id: str) -> Follow:
        alias = await self.aliases.get(alias_id)
        if alias is None:
            raise AliasNotFoundError()
        await self._check_enabled(alias.guild_id)

        if alias.internal_user_id == follower_internal_user_id:
            raise CannotFollowSelfError()
        if await self.follows.get(follower_internal_user_id, alias_id) is not None:
            raise AlreadyFollowingError()

        return await self.follows.create(follower_internal_user_id, alias_id, alias.guild_id)

    async def unfollow(self, *, follower_internal_user_id: str, alias_id: str) -> None:
        if not await self.follows.delete(follower_internal_user_id, alias_id):
            raise NotFollowingError()

    async def toggle(self, *, follower_internal_user_id: str, alias_id: str) -> bool:
        """Follow/unfollow in one action. Returns True when now following."""
        if await self.follows.get(follower_internal_user_id, alias_id) is not None:
            await self.unfollow(
                follower_internal_user_id=follower_internal_user_id, alias_id=alias_id
            )
            return False
        await self.follow(follower_internal_user_id=follower_internal_user_id, alias_id=alias_id)
        return True

    async def is_following(self, follower_internal_user_id: str, alias_id: str) -> bool:
        return await self.follows.get(follower_internal_user_id, alias_id) is not None

    async def follower_count(self, alias_id: str) -> int:
        return await self.follows.count_for_alias(alias_id)

    async def followers_to_notify(self, alias_id: str) -> list[str]:
        """Internal user ids to DM when this alias posts again."""
        return [
            follow.follower_internal_user_id
            for follow in await self.follows.list_followers(alias_id, notifications_only=True)
        ]

    async def following(
        self, follower_internal_user_id: str, guild_id: int | None = None
    ) -> list[tuple[Follow, AnonAlias]]:
        return await self.follows.list_following(follower_internal_user_id, guild_id)
