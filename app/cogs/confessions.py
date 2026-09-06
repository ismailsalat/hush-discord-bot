"""Private confession entry points."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from app.cogs.base import HushCog, dm_only, require_dm
from app.views.home import HomeView, start_confession
from app.views.picker import run_for_dm_guild


class ConfessionsCog(HushCog):
    @app_commands.command(name="confess", description="Send an anonymous confession.")
    @dm_only()
    async def confess(self, interaction: discord.Interaction) -> None:
        """Start a confession only from the user's one-to-one DM with Hush."""
        require_dm(interaction)

        async def action(inner: discord.Interaction, guild_id: int) -> None:
            await start_confession(inner, guild_id)

        await run_for_dm_guild(
            interaction,
            action,
            prompt="Choose where you want to post this confession.",
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """A plain DM opens the compact Hush home menu.

        The message body is not treated as a confession.  Confession content is
        typed into a modal so the user always sees a private preview/submit
        flow rather than accidentally posting whatever they DM the bot.
        """
        if message.author.bot or message.guild is not None:
            return

        runtime = runtime_of_bot(self.bot)
        try:
            await message.channel.send(
                embed=runtime.agreement_embeds.home(),
                view=HomeView(),
            )
        except discord.HTTPException:
            pass


def runtime_of_bot(bot: commands.Bot):
    return bot.runtime  # type: ignore[attr-defined]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ConfessionsCog(bot))
