"""Guild registration and settings access."""

from __future__ import annotations

from sqlalchemy import select

from app.config.settings import Settings
from app.core.exceptions import GuildNotConfiguredError
from app.database.models import Guild, GuildSettings
from app.database.repositories.base import BaseRepository


class GuildRepository(BaseRepository):
    async def get(self, guild_id: int) -> Guild | None:
        return await self.session.get(Guild, guild_id)

    async def get_or_create(self, guild_id: int, name: str | None = None) -> Guild:
        guild = await self.session.get(Guild, guild_id)
        if guild is None:
            guild = Guild(id=guild_id, name=name)
            self.session.add(guild)
            await self.session.flush()
        elif name and guild.name != name:
            guild.name = name
        return guild

    async def get_settings(self, guild_id: int) -> GuildSettings | None:
        return await self.session.get(GuildSettings, guild_id)

    async def get_or_create_settings(
        self, guild_id: int, settings: Settings, *, name: str | None = None
    ) -> GuildSettings:
        """Fetch settings, seeding a new row from environment defaults."""
        await self.get_or_create(guild_id, name)
        row = await self.session.get(GuildSettings, guild_id)
        if row is None:
            row = GuildSettings(
                guild_id=guild_id,
                rules_version=settings.rules_version,
                confession_character_limit=settings.default_confession_limit,
                alias_rotation_days=settings.default_alias_rotation_days,
                rating_scale_max=settings.rating_scale_max,
                moderator_role_ids=[],
            )
            self.session.add(row)
            await self.session.flush()
        return row

    async def list_configured(self) -> list[GuildSettings]:
        """Every guild with a confession channel set (used at startup)."""
        result = await self.session.execute(
            select(GuildSettings).where(GuildSettings.confession_channel_id.is_not(None))
        )
        return list(result.scalars().all())

    #: Only these may be changed through configuration commands. Anything else
    #: (ids, timestamps) is managed by the application, not by admins.
    MUTABLE_SETTINGS = frozenset(
        {
            "confession_channel_id",
            "mod_log_channel_id",
            "admin_role_ids",
            "admin_user_ids",
            "moderator_role_ids",
            "moderator_user_ids",
            "rules_version",
            "confession_character_limit",
            "alias_rotation_days",
            "rating_scale_min",
            "rating_scale_max",
            "ratings_enabled",
            "followers_enabled",
            "bookmarks_enabled",
            "polls_enabled",
            "updates_enabled",
            "trending_enabled",
        }
    )

    async def update_settings(self, guild_id: int, **values) -> GuildSettings:
        """Apply configuration changes to one guild.

        Unknown or protected keys raise rather than silently doing nothing, so a
        typo in a command surfaces immediately instead of looking successful.
        """
        settings = await self.get_settings(guild_id)
        if settings is None:
            raise GuildNotConfiguredError()

        unknown = set(values) - self.MUTABLE_SETTINGS
        if unknown:
            raise ValueError(f"not configurable: {sorted(unknown)}")

        for key, value in values.items():
            setattr(settings, key, value)
        await self.session.flush()
        return settings
