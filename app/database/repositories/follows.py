"""Follows. Always keyed to an alias, never to a user."""

from __future__ import annotations

from sqlalchemy import delete, func, select

from app.database.models import AnonAlias, Follow
from app.database.repositories.base import BaseRepository


class FollowRepository(BaseRepository):
    async def get(self, follower_internal_user_id: str, alias_id: str) -> Follow | None:
        result = await self.session.execute(
            select(Follow).where(
                Follow.follower_internal_user_id == follower_internal_user_id,
                Follow.alias_id == alias_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self, follower_internal_user_id: str, alias_id: str, guild_id: int
    ) -> Follow:
        follow = Follow(
            follower_internal_user_id=follower_internal_user_id,
            alias_id=alias_id,
            guild_id=guild_id,
        )
        self.session.add(follow)
        await self.session.flush()
        return follow

    async def delete(self, follower_internal_user_id: str, alias_id: str) -> bool:
        result = await self.session.execute(
            delete(Follow).where(
                Follow.follower_internal_user_id == follower_internal_user_id,
                Follow.alias_id == alias_id,
            )
        )
        return bool(result.rowcount)

    async def count_for_alias(self, alias_id: str) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Follow).where(Follow.alias_id == alias_id)
        )
        return int(result.scalar_one())

    async def list_followers(self, alias_id: str, *, notifications_only: bool = True) -> list[Follow]:
        """Followers of a single alias.

        Deliberately scoped to one alias id: a rotated alias has no followers,
        which is exactly what preserves the privacy reset.
        """
        query = select(Follow).where(Follow.alias_id == alias_id)
        if notifications_only:
            query = query.where(Follow.notifications_enabled.is_(True))
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def list_following(
        self, follower_internal_user_id: str, guild_id: int | None = None
    ) -> list[tuple[Follow, AnonAlias]]:
        query = (
            select(Follow, AnonAlias)
            .join(AnonAlias, AnonAlias.id == Follow.alias_id)
            .where(Follow.follower_internal_user_id == follower_internal_user_id)
        )
        if guild_id is not None:
            query = query.where(Follow.guild_id == guild_id)
        result = await self.session.execute(query.order_by(Follow.created_at.desc()))
        return [(row[0], row[1]) for row in result.all()]

    async def set_notifications(
        self, follower_internal_user_id: str, alias_id: str, enabled: bool
    ) -> None:
        follow = await self.get(follower_internal_user_id, alias_id)
        if follow is not None:
            follow.notifications_enabled = enabled
            await self.session.flush()
