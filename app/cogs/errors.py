"""Global command error handling.

Without this, a raised exception inside a slash command produces a silent
"application did not respond". Every failure gets an embed, and unexpected ones
get a short error id that matches a full stack trace in the log.
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from app.cogs.base import HushCog
from app.core.exceptions import HushError
from app.logging.error_ids import report_exception
from app.views.common import respond


class ErrorsCog(HushCog):
    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self._previous = bot.tree.on_error
        bot.tree.on_error = self.on_app_command_error  # type: ignore[assignment]

    async def cog_unload(self) -> None:
        self.bot.tree.on_error = self._previous  # type: ignore[assignment]

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        runtime = self.runtime
        original = getattr(error, "original", error)

        if isinstance(original, HushError):
            embed = runtime.error_embeds.from_exception(original)
        elif isinstance(error, app_commands.CommandOnCooldown):
            embed = runtime.error_embeds.rate_limited(
                f"Try that again in {error.retry_after:.0f} seconds."
            )
        elif isinstance(error, (app_commands.MissingPermissions, app_commands.CheckFailure)):
            embed = runtime.error_embeds.generic(
                "Not allowed", "You don't have permission to use that command."
            )
        else:
            report = report_exception(
                original,
                operation="app_command",
                command=getattr(interaction.command, "qualified_name", None),
                guild_id=interaction.guild_id,
            )
            embed = runtime.error_embeds.from_report(report)

        await respond(interaction, embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ErrorsCog(bot))
