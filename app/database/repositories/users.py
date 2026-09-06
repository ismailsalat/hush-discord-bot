"""Internal user and guild membership access."""

from __future__ import annotations

from sqlalchemy import select, update

from app.database.models import GuildMembership, User
from app.database.repositories.base import BaseRepository
from app.utils.time import utcnow


class UserRepository(BaseRepository):
    async def get(self, internal_user_id: str) -> User | None:
        return await self.session.get(User, internal_user_id)

    async def get_by_discord_id(self, discord_user_id: int) -> User | None:
        result = await self.session.execute(
            select(User).where(User.discord_user_id == discord_user_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, discord_user_id: int) -> User:
        """Return the internal user for a Discord id, creating it on first sight.

        Handles the race where two interactions arrive at once by retrying the
        lookup after a unique-constraint failure.
        """
        existing = await self.get_by_discord_id(discord_user_id)
        if existing is not None:
            return existing

        user = User(discord_user_id=discord_user_id)
        self.session.add(user)
        try:
            await self.session.flush()
        except Exception:
            await self.session.rollback()
            found = await self.get_by_discord_id(discord_user_id)
            if found is None:
                raise
            return found
        return user

    async def touch(self, internal_user_id: str) -> None:
        await self.session.execute(
            update(User).where(User.id == internal_user_id).values(last_seen_at=utcnow())
        )

    async def set_globally_blocked(self, internal_user_id: str, blocked: bool) -> None:
        await self.session.execute(
            update(User).where(User.id == internal_user_id).values(is_globally_blocked=blocked)
        )

    # --- Memberships -------------------------------------------------------

    async def ensure_membership(self, internal_user_id: str, guild_id: int) -> GuildMembership:
        result = await self.session.execute(
            select(GuildMembership).where(
                GuildMembership.internal_user_id == internal_user_id,
                GuildMembership.guild_id == guild_id,
            )
        )
        membership = result.scalar_one_or_none()
        if membership is None:
            membership = GuildMembership(
                internal_user_id=internal_user_id, guild_id=guild_id, last_active_at=utcnow()
            )
            self.session.add(membership)
            await self.session.flush()
        else:
            membership.last_active_at = utcnow()
        return membership

    async def list_guild_ids(self, internal_user_id: str) -> list[int]:
        """Guilds this user has used Hush in (drives the DM guild picker)."""
        result = await self.session.execute(
            select(GuildMembership.guild_id)
            .where(GuildMembership.internal_user_id == internal_user_id)
            .order_by(GuildMembership.last_active_at.desc().nullslast())
        )
        return list(result.scalars().all())

    async def get_by_internal_id(self, internal_user_id: str) -> User | None:
        """Reverse lookup used only by the notification dispatcher and exports."""
        result = await self.session.execute(select(User).where(User.id == internal_user_id))
        return result.scalar_one_or_none()
