"""The About page and the admin status board.

Every value here is read live - guild count from the client, uptime from the
process start time, version from ``app.__version__``. Nothing is hard-coded or
faked.
"""

from __future__ import annotations

import discord

from app.__version__ import __author__, __tagline__
from app.embeds.factory import Colors, EmbedFactory, subtext
from app.utils.time import format_duration, utcnow


class AboutEmbedBuilder:
    def __init__(self, factory: EmbedFactory):
        self.factory = factory

    def about(
        self,
        *,
        version: str,
        guild_count: int,
        started_at,
        healthy: bool = True,
    ) -> discord.Embed:
        brand = self.factory.brand
        embed = self.factory.base(
            title=brand,
            description=(
                f"**{__tagline__}**\n\n"
                f"{brand} lets communities share anonymous confessions, rate posts, "
                "follow anonymous profiles, bookmark confessions, post updates and "
                "create polls, while keeping public identities hidden."
            ),
            color=Colors.BRAND,
        )

        embed.add_field(name="Version", value=f"v{version}", inline=True)
        embed.add_field(
            name="Status", value="Online" if healthy else "Degraded", inline=True
        )
        embed.add_field(name="Servers", value=f"{guild_count:,}", inline=True)
        embed.add_field(
            name="Uptime", value=format_duration(utcnow() - started_at), inline=True
        )
        embed.add_field(name="Developer", value=__author__, inline=True)
        embed.add_field(
            name="Privacy",
            value=(
                f"Anonymous to regular server members.\n"
                f"{subtext(brand + ' privately retains account mappings for moderation, abuse prevention and system integrity.')}"
            ),
            inline=False,
        )
        embed.set_footer(text="Built with privacy-conscious moderation in mind.")
        return embed

    def status(
        self,
        *,
        report,
        guild_count: int,
        started_at,
        version: str,
        channel_configured: bool,
        mod_log_configured: bool,
        pending_notifications: int,
        errors_last_hour: int,
        last_backup: str,
    ) -> discord.Embed:
        """Live operational status for `/admin status`."""

        def mark(ok: bool, yes: str, no: str) -> str:
            return f"{'\u2705' if ok else '\u274c'} {yes if ok else no}"

        database_ok = next(
            (check.ok for check in report.checks if check.name.lower().startswith("data")),
            False,
        )
        discord_ok = next(
            (check.ok for check in report.checks if check.name.lower() == "discord"), True
        )
        backups_ok = next(
            (check.ok for check in report.checks if check.name.lower() == "backups"), True
        )

        embed = self.factory.base(
            title=f"{self.factory.brand} status",
            color=Colors.SUCCESS if report.healthy else Colors.ERROR,
        )
        embed.add_field(name="Database", value=mark(database_ok, "Healthy", "Unreachable"), inline=True)
        embed.add_field(name="Discord", value=mark(discord_ok, "Connected", "Disconnected"), inline=True)
        embed.add_field(name="Backups", value=mark(backups_ok, "Healthy", "Attention needed"), inline=True)

        embed.add_field(
            name="Confession Channel",
            value=mark(channel_configured, "Configured", "Not set"),
            inline=True,
        )
        embed.add_field(
            name="Mod Log",
            value=mark(mod_log_configured, "Configured", "Not set"),
            inline=True,
        )
        embed.add_field(name="Last Backup", value=last_backup, inline=True)

        embed.add_field(name="Pending Notifications", value=str(pending_notifications), inline=True)
        embed.add_field(name="Errors Last Hour", value=str(errors_last_hour), inline=True)
        embed.add_field(
            name="Uptime", value=format_duration(utcnow() - started_at), inline=True
        )

        embed.set_footer(text=f"{self.factory.brand} v{version} \u00b7 {guild_count:,} servers")
        return embed


def link_view(links: dict[str, str]) -> discord.ui.View | None:
    """Build the About page's link buttons.

    Returns ``None`` when nothing is configured, so an operator who has not set
    any URLs never sees an empty button row.
    """
    if not links:
        return None
    view = discord.ui.View(timeout=None)
    for label, url in links.items():
        view.add_item(discord.ui.Button(label=label, url=url, style=discord.ButtonStyle.link))
    return view
