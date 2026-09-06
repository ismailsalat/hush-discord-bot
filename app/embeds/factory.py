"""Central embed styling.

Every embed in Hush is built here or by a builder that starts here, so
colour, footer and typography stay consistent without duplicated styling code.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

import discord

from app.config.settings import Settings
from app.security.privacy import anonymity_notice

SEPARATOR: Final[str] = "\u2500" * 18
BULLET: Final[str] = "\u00b7"


class Colors:
    """Palette. Each surface has one meaning and one colour."""

    BRAND = 0x8B7CF6      # violet - confessions, profiles, neutral brand surfaces
    SUCCESS = 0x22C55E    # green  - agreement, posted confirmations
    INFO = 0x3B82F6       # blue   - bookmarks, informational notices
    WARNING = 0xF59E0B    # amber  - moderation warnings
    ERROR = 0xEF4444      # red    - failures, bans, reports
    GOLD = 0xEAB308       # gold   - hall of fame
    MUTED = 0x4B5563      # grey   - disabled / unavailable states


def subtext(text: str) -> str:
    """Discord small-text markdown, used for secondary lines."""
    return f"-# {text}"


class EmbedFactory:
    """Builds branded embeds. Instantiated once and shared."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.brand = settings.brand_name
        self.tagline = settings.brand_tagline

    # --- Base ---------------------------------------------------------------

    def base(
        self,
        *,
        title: str | None = None,
        description: str | None = None,
        color: int = Colors.BRAND,
        footer: str | None = None,
        timestamp: datetime | None = None,
    ) -> discord.Embed:
        embed = discord.Embed(title=title, description=description, color=color)
        if footer:
            embed.set_footer(text=footer)
        if timestamp:
            embed.timestamp = timestamp
        return embed

    # --- Generic states -----------------------------------------------------

    def success(self, title: str, description: str | None = None) -> discord.Embed:
        return self.base(title=f"\u2705 {title}", description=description, color=Colors.SUCCESS)

    def info(self, title: str, description: str | None = None) -> discord.Embed:
        return self.base(title=title, description=description, color=Colors.INFO)

    def warning(self, title: str, description: str | None = None) -> discord.Embed:
        return self.base(title=f"\u26a0 {title}", description=description, color=Colors.WARNING)

    def error(
        self, title: str = "Something went wrong", description: str | None = None,
        error_id: str | None = None,
    ) -> discord.Embed:
        """User-facing failure. Never leaks a traceback - only a short code."""
        embed = self.base(
            title=f"\u274c {title}",
            description=description or "That action could not be completed right now.",
            color=Colors.ERROR,
        )
        if error_id:
            embed.add_field(name="Error ID", value=f"`{error_id}`", inline=False)
            embed.set_footer(text="Share this ID with an administrator if it keeps happening.")
        return embed

    def unavailable(self, message: str = "This confession is no longer available.") -> discord.Embed:
        return self.base(title="\u26a0 Unavailable", description=message, color=Colors.MUTED)

    # --- Anonymity note -----------------------------------------------------

    @property
    def anonymity_line(self) -> str:
        return anonymity_notice(self.brand)

    def with_anonymity_footer(self, embed: discord.Embed) -> discord.Embed:
        embed.set_footer(text=self.settings.brand_privacy_note)
        return embed
