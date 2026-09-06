"""Admin surfaces: setup, health, backups, exports."""

from __future__ import annotations

import discord

from app.database.models import GuildSettings
from app.embeds.factory import Colors, EmbedFactory, subtext
from app.services.health_service import HealthReport


class AdminEmbedBuilder:
    def __init__(self, factory: EmbedFactory):
        self.factory = factory

    def health(self, report: HealthReport) -> discord.Embed:
        embed = self.factory.base(
            title=f"{self.factory.brand} health",
            color=Colors.SUCCESS if report.healthy else Colors.ERROR,
        )
        embed.description = "\n".join(
            f"{check.icon} **{check.name}**"
            + (f" {subtext(check.detail)}" if check.detail else "")
            for check in report.checks
        )
        if report.metrics:
            embed.add_field(
                name="\u200b",
                value="\n".join(f"**{key}:** {value}" for key, value in report.metrics.items()),
                inline=False,
            )
        return embed

    def settings(self, settings: GuildSettings, *, guild_name: str) -> discord.Embed:
        embed = self.factory.base(
            title=f"{self.factory.brand} settings \u00b7 {guild_name}", color=Colors.BRAND
        )
        channel = (
            f"<#{settings.confession_channel_id}>" if settings.confession_channel_id else "not set"
        )
        mod_log = (
            f"<#{settings.mod_log_channel_id}>" if settings.mod_log_channel_id else "not set"
        )
        roles = (
            ", ".join(f"<@&{role_id}>" for role_id in settings.moderator_role_ids)
            or "server administrators only"
        )

        embed.add_field(name="Confession channel", value=channel, inline=True)
        embed.add_field(name="Mod log channel", value=mod_log, inline=True)
        embed.add_field(name="Moderator roles", value=roles, inline=False)
        embed.add_field(name="Rules version", value=str(settings.rules_version), inline=True)
        embed.add_field(
            name="Character limit", value=f"{settings.confession_character_limit:,}", inline=True
        )
        embed.add_field(
            name="Alias rotation", value=f"{settings.alias_rotation_days} days", inline=True
        )

        toggles = {
            "Ratings": settings.ratings_enabled,
            "Followers": settings.followers_enabled,
            "Bookmarks": settings.bookmarks_enabled,
            "Polls": settings.polls_enabled,
            "Updates": settings.updates_enabled,
        }
        embed.add_field(
            name="Features",
            value="  ".join(
                f"{'\u2705' if enabled else '\u274c'} {name}" for name, enabled in toggles.items()
            ),
            inline=False,
        )
        return embed

    def backup_list(self, records: list) -> discord.Embed:
        if not records:
            return self.factory.base(
                title="Backups", description="No backups found yet.", color=Colors.WARNING
            )
        lines = [
            f"**{record.name}**\n{subtext(f'{record.tier} \u00b7 {record.size_display}')}"
            for record in records[:10]
        ]
        return self.factory.base(
            title=f"Backups ({len(records)})", description="\n".join(lines), color=Colors.INFO
        )

    def backup_verification(self, report) -> discord.Embed:
        embed = self.factory.base(
            title=f"Backup verification \u00b7 {report.summary}",
            description="\n".join(
                f"{'\u2705' if ok else '\u274c'} **{name}** {subtext(detail)}"
                for name, ok, detail in report.checks
            ),
            color=Colors.SUCCESS if report.ok else Colors.ERROR,
        )
        if report.row_counts:
            populated = {k: v for k, v in report.row_counts.items() if v > 0}
            if populated:
                embed.add_field(
                    name="Row counts",
                    value=", ".join(f"{k}: {v}" for k, v in list(populated.items())[:12]),
                    inline=False,
                )
        return embed

    def export_ready(self, *, filename: str, size_bytes: int, row_counts: dict, redacted: bool):
        embed = self.factory.success(
            "Export ready", f"`{filename}` \u00b7 {size_bytes / 1024:.1f} KB"
        )
        total = sum(row_counts.values())
        embed.add_field(
            name="Contents",
            value=", ".join(f"{name}: {count}" for name, count in row_counts.items() if count)
            or "no rows",
            inline=False,
        )
        embed.add_field(name="Total rows", value=str(total), inline=True)
        if redacted:
            embed.add_field(
                name="\u200b",
                value=subtext(
                    "Discord user IDs were removed - your permission level does not "
                    "include identity data."
                ),
                inline=False,
            )
        embed.set_footer(text="This file expires automatically. Every export is logged.")
        return embed
