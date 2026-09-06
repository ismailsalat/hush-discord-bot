"""The DM-only /about command."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from app.cogs.base import HushCog, dm_only, require_dm
from app.embeds.about import link_view
from app.views.common import respond


class AboutCog(HushCog):
    @app_commands.command(name="about", description="About Hush.")
    @dm_only()
    async def about(self, interaction: discord.Interaction) -> None:
        require_dm(interaction)
        runtime = self.runtime
        await interaction.response.defer(ephemeral=True)

        report = await runtime.health.run()
        embed = runtime.about_embeds.about(
            version=runtime.settings.version,
            guild_count=len(self.bot.guilds),
            started_at=runtime.started_at,
            healthy=report.healthy,
        )
        await respond(
            interaction,
            embed=embed,
            view=link_view(runtime.settings.links),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AboutCog(bot))
