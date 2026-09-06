"""Shared cog helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

import discord
from discord import app_commands
from discord.ext import commands

from app.core.runtime import Runtime

T = TypeVar("T")


class HushCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def runtime(self) -> Runtime:
        return self.bot.runtime  # type: ignore[attr-defined]


def guild_only_id(interaction: discord.Interaction) -> int:
    """The guild this interaction belongs to, or raise a friendly error."""
    from app.core.exceptions import GuildOnlyError

    if interaction.guild_id is None:
        raise GuildOnlyError()
    return interaction.guild_id


def require_dm(interaction: discord.Interaction) -> None:
    """Runtime safety net for commands that must stay inside Hush DMs.

    Discord also receives the command-context restriction through
    :func:`dm_only`, so these commands should not normally be offered in a
    server at all.  This check is kept as defence in depth for stale command
    caches and older clients.
    """
    from app.core.exceptions import DMOnlyError

    if interaction.guild_id is not None:
        raise DMOnlyError()


def dm_only() -> Callable[[T], T]:
    """Make a top-level application command available only in bot DMs.

    ``private_channels=False`` intentionally excludes group DMs.  Hush's
    private user flow should happen in the one-to-one conversation with the
    bot, while moderation and administration stay in servers.
    """
    return app_commands.allowed_contexts(
        guilds=False,
        dms=True,
        private_channels=False,
    )
