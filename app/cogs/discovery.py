"""DM-only trending and Hall of Fame commands."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from app.cogs.base import HushCog, dm_only, require_dm
from app.views.common import respond
from app.views.gate import ensure_ready
from app.views.picker import run_for_dm_guild


class DiscoveryCog(HushCog):
    @app_commands.command(name="trending", description="See what's getting reactions right now.")
    @dm_only()
    async def trending(self, interaction: discord.Interaction) -> None:
        require_dm(interaction)

        async def action(inner: discord.Interaction, guild_id: int) -> None:
            runtime = self.runtime
            actor = await ensure_ready(inner, guild_id)
            if actor is None:
                return

            from app.services.trending_service import TrendingService

            async with runtime.session() as session:
                entries = await TrendingService(session).trending(
                    guild_id, limit=runtime.settings.trending_limit
                )
            await respond(
                inner,
                embed=runtime.profile_embeds.trending(
                    entries,
                    window_hours=runtime.settings.trending_window_hours,
                ),
            )

        await run_for_dm_guild(
            interaction,
            action,
            prompt="Choose which server's trending confessions you want to see.",
        )

    @app_commands.command(
        name="halloffame",
        description="See the highest rated, most rated and most discussed confessions.",
    )
    @dm_only()
    async def halloffame(self, interaction: discord.Interaction) -> None:
        require_dm(interaction)

        async def action(inner: discord.Interaction, guild_id: int) -> None:
            runtime = self.runtime
            actor = await ensure_ready(inner, guild_id)
            if actor is None:
                return

            from app.services.trending_service import TrendingService

            async with runtime.session() as session:
                hall = await TrendingService(session).hall_of_fame(guild_id)
            await respond(inner, embed=runtime.profile_embeds.hall_of_fame(hall))

        await run_for_dm_guild(
            interaction,
            action,
            prompt="Choose which server's Hall of Fame you want to see.",
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DiscoveryCog(bot))
