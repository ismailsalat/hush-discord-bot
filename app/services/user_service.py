"""Resolution of Discord identities into internal, anonymous-safe identities."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.database.models import GuildSettings, User
from app.database.repositories import GuildRepository, UserRepository


@dataclass(frozen=True, slots=True)
class UserContext:
    """A resolved actor. ``internal_id`` is used everywhere downstream."""

    internal_id: str
    discord_user_id: int
    guild_id: int | None = None


class UserService:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)
        self.guilds = GuildRepository(session)

    async def resolve(self, discord_user_id: int, guild_id: int | None = None) -> UserContext:
        """Return the internal identity for a Discord user, creating it if new."""
        user = await self.users.get_or_create(discord_user_id)
        await self.users.touch(user.id)
        if guild_id is not None:
            await self.users.ensure_membership(user.id, guild_id)
        return UserContext(internal_id=user.id, discord_user_id=discord_user_id, guild_id=guild_id)

    async def get_by_internal_id(self, internal_user_id: str) -> User | None:
        return await self.users.get(internal_user_id)

    async def ensure_guild(self, guild_id: int, name: str | None = None) -> GuildSettings:
        return await self.guilds.get_or_create_settings(guild_id, self.settings, name=name)

    async def known_guild_ids(self, internal_user_id: str) -> list[int]:
        """Guilds previously verified for this internal Hush identity."""
        return await self.users.list_guild_ids(internal_user_id)

    async def remember_guild(self, internal_user_id: str, guild_id: int) -> None:
        """Persist a verified mutual-guild relationship for faster DM flows."""
        await self.users.ensure_membership(internal_user_id, guild_id)

    async def lookup_discord_id(self, internal_user_id: str) -> int | None:
        """Privileged reverse lookup.

        Callers must have already checked ``IDENTITY_LOOKUP_LEVEL`` and must log
        the lookup. Nothing here is exposed to ordinary moderation flows.
        """
        user = await self.users.get(internal_user_id)
        return user.discord_user_id if user else None
