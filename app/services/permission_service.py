"""Centralized permission resolution for Discord interactions.

This is the only place that turns a ``discord.Interaction`` into a
:class:`PermissionLevel`. Commands declare what they need with the
:func:`requires` decorator and never re-implement a check.
"""

from __future__ import annotations

import functools
from typing import Awaitable, Callable

import discord
from discord import app_commands

from app.core.constants import PermissionLevel
from app.core.exceptions import GuildOnlyError
from app.security.permissions import GuildRoleConfig, MemberContext, require, resolve_level


def member_context(interaction: discord.Interaction) -> MemberContext:
    """Build a Discord-free description of the caller."""
    member = interaction.user
    guild = interaction.guild
    return MemberContext(
        user_id=member.id,
        role_ids=frozenset(role.id for role in getattr(member, "roles", ())),
        is_guild_admin=bool(
            getattr(getattr(member, "guild_permissions", None), "administrator", False)
        ),
        is_guild_owner=bool(guild and guild.owner_id == member.id),
    )


async def resolve_permission_level(interaction: discord.Interaction) -> PermissionLevel:
    """Resolve the caller's Hush permission tier.

    Works in DMs too: without a guild there is no guild configuration, so only
    the bot-owner list can raise someone above ``USER``.
    """
    runtime = interaction.client.runtime  # type: ignore[attr-defined]

    config = GuildRoleConfig()
    if interaction.guild_id is not None:
        async with runtime.session() as session:
            from app.database.repositories import GuildRepository

            settings = await GuildRepository(session).get_settings(interaction.guild_id)
        config = GuildRoleConfig.from_settings(settings)

    return resolve_level(
        member_context(interaction),
        owner_ids=runtime.settings.bot_owner_ids,
        guild_config=config,
    )


def requires(
    level: PermissionLevel,
    *,
    action: str = "use this",
    guild_only: bool = True,
    defer: bool = True,
) -> Callable:
    """Gate a command callback behind a permission tier.

    Applied *below* the ``@app_commands.command`` decorator. Deferring here
    means a slow permission lookup cannot blow Discord's three second deadline,
    and a denied caller still gets a friendly ephemeral embed rather than
    "application did not respond".
    """

    def decorator(func: Callable[..., Awaitable[None]]) -> Callable[..., Awaitable[None]]:
        @functools.wraps(func)
        async def wrapper(self, interaction: discord.Interaction, *args, **kwargs):
            if guild_only and interaction.guild_id is None:
                raise GuildOnlyError()
            if defer and not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)

            actual = await resolve_permission_level(interaction)
            require(actual, level, action=action)
            return await func(self, interaction, *args, **kwargs)

        wrapper.__hush_required_level__ = level  # type: ignore[attr-defined]
        return wrapper

    return decorator


def owner_only() -> Callable:
    """Shorthand for ``/owner`` commands, which are never guild-scoped."""
    return requires(
        PermissionLevel.BOT_OWNER, action="use owner commands", guild_only=False
    )


async def is_bot_owner_interaction(interaction: discord.Interaction) -> bool:
    """Used to hide owner commands from everyone else in the command list."""
    runtime = interaction.client.runtime  # type: ignore[attr-defined]
    return interaction.user.id in set(runtime.settings.bot_owner_ids)


def hide_from_non_owners(command: app_commands.Command) -> app_commands.Command:
    """Mark a command as owner-only for Discord's own permission gating."""
    command.default_permissions = discord.Permissions(administrator=True)
    return command
