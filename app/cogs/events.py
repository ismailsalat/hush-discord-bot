"""Passive Discord events.

Two jobs: keep the reply count on confessions accurate, and keep the record of
which servers a user belongs to fresh so DM flows know where to send things.
"""

from __future__ import annotations

import discord
from discord.ext import commands

from app.cogs.base import HushCog
from app.logging.error_ids import report_exception
from app.logging.setup import app_logger


class EventsCog(HushCog):
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Count replies to confession messages.

        Uses ``message.reference`` only, which needs no message content intent -
        we never read what people write in the channel.
        """
        if message.author.bot or message.guild is None:
            return
        reference = message.reference
        if reference is None or reference.message_id is None:
            return

        try:
            from app.services.confession_service import ConfessionService

            async with self.runtime.session() as session:
                confession = await ConfessionService(
                    session, self.runtime.settings
                ).register_reply(reference.message_id)

            if confession is not None and self.runtime.publishing is not None:
                await self.runtime.publishing.refresh_message(confession.id)
        except Exception as exc:  # pragma: no cover - never break on a stray message
            report_exception(exc, operation="events.reply_count", guild_id=message.guild.id)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        """Record membership so DM flows can offer the right servers."""
        if interaction.guild_id is None:
            return
        try:
            from app.services.user_service import UserService

            async with self.runtime.session() as session:
                await UserService(session, self.runtime.settings).resolve(
                    interaction.user.id, interaction.guild_id
                )
        except Exception:  # pragma: no cover
            pass

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        async with self.runtime.session() as session:
            from app.database.repositories import GuildRepository

            await GuildRepository(session).get_or_create_settings(
                guild.id, self.runtime.settings, name=guild.name
            )
        app_logger().info("guild_joined", guild_id=guild.id, members=guild.member_count)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        app_logger().info("guild_removed", guild_id=guild.id)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        """If the confession channel disappears, unset it rather than fail forever."""
        async with self.runtime.session() as session:
            from app.database.repositories import GuildRepository

            guilds = GuildRepository(session)
            settings = await guilds.get_settings(channel.guild.id)
            if settings and settings.confession_channel_id == channel.id:
                await guilds.update_settings(channel.guild.id, confession_channel_id=None)
                app_logger().warning(
                    "confession_channel_deleted", guild_id=channel.guild.id, channel_id=channel.id
                )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EventsCog(bot))
