"""Maps domain exceptions onto friendly embeds.

Every user-facing failure goes through here, which is what guarantees no button
ever fails silently and no traceback ever reaches a user.
"""

from __future__ import annotations

import discord

from app.core.exceptions import (
    AliasRotationCooldownError,
    HushError,
    MissingChannelPermissionsError,
    UserHushBannedError,
)
from app.embeds.factory import Colors, EmbedFactory
from app.logging.error_ids import ErrorReport
from app.utils.time import discord_timestamp


class ErrorEmbedBuilder:
    def __init__(self, factory: EmbedFactory):
        self.factory = factory

    def from_exception(self, exc: HushError) -> discord.Embed:
        """Render a known domain error using its own user-facing wording."""
        if isinstance(exc, UserHushBannedError):
            embed = self.factory.base(
                title=f"\U0001f512 You currently cannot use {self.factory.brand}",
                description=exc.user_message,
                color=Colors.ERROR,
            )
            if exc.permanent:
                embed.add_field(name="Duration", value="Permanent", inline=True)
            elif exc.expires_at is not None:
                embed.add_field(
                    name="Ban expires",
                    value=discord_timestamp(exc.expires_at, "F"),
                    inline=True,
                )
            if exc.reason:
                embed.add_field(name="Reason", value=exc.reason, inline=False)
            return embed

        if isinstance(exc, AliasRotationCooldownError):
            embed = self.factory.base(
                title=f"\u26a0 {exc.user_title}",
                description=exc.user_message,
                color=Colors.WARNING,
            )
            embed.add_field(
                name="Next rotation available",
                value=discord_timestamp(exc.available_at, "F"),
                inline=False,
            )
            return embed

        if isinstance(exc, MissingChannelPermissionsError):
            missing = "\n".join(f"\u2022 {item}" for item in exc.missing)
            return self.factory.base(
                title="\u26a0 Missing permissions",
                description=(
                    f"{self.factory.brand} cannot post in {exc.channel_mention}.\n\n"
                    f"An administrator needs to restore:\n{missing}"
                ),
                color=Colors.ERROR,
            )

        color = Colors.WARNING if exc.expected else Colors.ERROR
        return self.factory.base(
            title=exc.user_title, description=exc.user_message, color=color
        )

    def from_report(self, report: ErrorReport) -> discord.Embed:
        """Unexpected failure: show a short code, log the rest."""
        return self.factory.error(
            "Something went wrong",
            "That action could not be completed right now. Please try again.",
            error_id=report.error_id,
        )

    def posting_failed(self, *, error_id: str | None = None) -> discord.Embed:
        embed = self.factory.error(
            "Something went wrong",
            "Your confession was **not** posted, but your draft was saved.",
            error_id=error_id,
        )
        return embed

    def already_rated(self, value: int, scale_max: int) -> discord.Embed:
        return self.factory.base(
            title="You already rated this confession",
            description=f"Your current rating: **{value}/{scale_max}**",
            color=Colors.INFO,
        )

    def rate_limited(self, message: str) -> discord.Embed:
        return self.factory.base(
            title="\u26a0 Slow down a moment", description=message, color=Colors.WARNING
        )

    def channel_missing(self, brand: str) -> discord.Embed:
        return self.factory.base(
            title="\u26a0 Not set up yet",
            description=(
                f"{brand} has not been set up in this server yet.\n\n"
                "An administrator needs to run `/admin setup`."
            ),
            color=Colors.MUTED,
        )

    def generic(self, title: str, message: str) -> discord.Embed:
        return self.factory.base(
            title=title, description=message, color=Colors.MUTED
        )

    def dm_required(self) -> discord.Embed:
        return self.factory.base(
            title="Check your DMs",
            description=f"{self.factory.brand} works in your direct messages to keep "
            "submissions private.",
            color=Colors.INFO,
        )

    def dm_blocked(self) -> discord.Embed:
        return self.factory.base(
            title="\u26a0 I can't DM you",
            description=(
                "Your privacy settings are blocking direct messages from this server, so "
                f"{self.factory.brand} cannot open a private submission for you.\n\n"
                "Enable **Direct Messages** in this server's privacy settings and try again."
            ),
            color=Colors.WARNING,
        )
