"""Moderation-facing embeds: warnings, bans, reports, mod log and history."""

from __future__ import annotations

from datetime import datetime

import discord

from app.core.constants import ReportReason
from app.embeds.factory import Colors, EmbedFactory, subtext
from app.services.dto import PunishmentHistory
from app.utils.time import discord_timestamp


class ModerationEmbedBuilder:
    def __init__(self, factory: EmbedFactory):
        self.factory = factory

    # --- User-facing notices ------------------------------------------------

    def warning_notice(self, *, reason: str, guild_name: str | None = None) -> discord.Embed:
        brand = self.factory.brand
        embed = self.factory.base(
            title=f"\u26a0 {brand} Warning",
            description=(
                "One of your submissions violated "
                f"{'**' + guild_name + '**' if guild_name else 'the server'}'s confession rules."
            ),
            color=Colors.WARNING,
        )
        embed.add_field(name="Reason", value=reason or "Not specified", inline=False)
        embed.add_field(
            name="\u200b",
            value=subtext(
                "Further violations may result in losing access to anonymous features."
            ),
            inline=False,
        )
        return embed

    def ban_notice(
        self,
        *,
        duration: str,
        reason: str,
        guild_name: str | None = None,
        expires_at: datetime | None = None,
    ) -> discord.Embed:
        brand = self.factory.brand
        where = f" in **{guild_name}**" if guild_name else ""
        embed = self.factory.base(
            title=f"\U0001f512 {brand} Access Suspended",
            description=f"You can no longer submit anonymous content{where}.",
            color=Colors.ERROR,
        )
        embed.add_field(name="Duration", value=duration, inline=True)
        if expires_at is not None:
            embed.add_field(name="Expires", value=discord_timestamp(expires_at, "f"), inline=True)
        embed.add_field(name="Reason", value=reason or "Not specified", inline=False)
        embed.add_field(
            name="\u200b",
            value=subtext(
                "If you believe this is a mistake, contact a moderator of that server. "
                f"This does not affect your Discord membership - only {brand}."
            ),
            inline=False,
        )
        return embed

    def ban_revoked(self, guild_name: str | None = None) -> discord.Embed:
        where = f" in **{guild_name}**" if guild_name else ""
        return self.factory.success(
            "Access restored", f"You can use {self.factory.brand} again{where}."
        )

    def confession_removed_notice(
        self, *, public_number: int, reason: str | None
    ) -> discord.Embed:
        embed = self.factory.base(
            title="Your confession was removed",
            description=f"Confession **#{public_number}** was removed by a moderator.",
            color=Colors.WARNING,
        )
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)
        return embed

    def pending_notice_intro(self) -> discord.Embed:
        return self.factory.base(
            title="\u2139 You have a new notice",
            description=(
                "You have a moderation notice, but it could not be delivered to your DMs "
                "earlier.\n\nPlease review it below."
            ),
            color=Colors.INFO,
        )

    def dm_closed_hint(self) -> discord.Embed:
        return self.factory.base(
            title="\u2139 We couldn't reach your DMs",
            description=(
                "Please open your DMs for this server to receive important notices from "
                f"{self.factory.brand}."
            ),
            color=Colors.INFO,
        )

    def follower_update(
        self, *, alias_display: str, public_number: int, message_link: str | None
    ) -> discord.Embed:
        embed = self.factory.base(
            title=f"{alias_display} posted a new confession",
            description=f"Confession **#{public_number}** is live.",
            color=Colors.BRAND,
        )
        if message_link:
            embed.add_field(name="\u200b", value=f"[View confession]({message_link})", inline=False)
        embed.set_footer(text="You are following this anonymous profile.")
        return embed

    # --- Moderator-facing ---------------------------------------------------

    def report_confirmation(self) -> discord.Embed:
        return self.factory.success(
            "Report submitted",
            "Thanks. Moderators will review this. Reporting does not automatically remove "
            "a confession.",
        )

    def report_form_intro(self) -> discord.Embed:
        return self.factory.base(
            title="Report confession",
            description="Why are you reporting this confession?",
            color=Colors.ERROR,
        )

    def mod_log(
        self,
        *,
        action: str,
        alias_display: str | None,
        moderator: str,
        reason: str | None,
        confession_number: int | None = None,
        punishment: str | None = None,
        record_id: str | None = None,
    ) -> discord.Embed:
        """Mod log entry. Shows the alias, never the Discord identity."""
        embed = self.factory.base(
            title=f"Moderation \u00b7 {action}",
            color=Colors.WARNING,
        )
        if confession_number is not None:
            embed.add_field(name="Confession", value=f"#{confession_number}", inline=True)
        if alias_display:
            embed.add_field(name="Account", value=alias_display, inline=True)
        embed.add_field(name="Moderator", value=moderator, inline=True)
        if punishment:
            embed.add_field(name="Punishment", value=punishment, inline=True)
        embed.add_field(name="Reason", value=reason or "Not specified", inline=False)
        if record_id:
            embed.set_footer(text=f"Record {record_id}")
        return embed

    def report_queue(self, rows: list[tuple[str, int, ReportReason, str]]) -> discord.Embed:
        if not rows:
            return self.factory.base(
                title="Report queue",
                description="No open reports. Nice.",
                color=Colors.SUCCESS,
            )
        lines = [
            f"**#{number}** \u00b7 {reason.label}\n{subtext(preview)}"
            for _report_id, number, reason, preview in rows
        ]
        return self.factory.base(
            title=f"Report queue ({len(rows)} open)",
            description="\n\n".join(lines),
            color=Colors.ERROR,
        )

    def history(self, history: PunishmentHistory) -> discord.Embed:
        """Moderator view of an account. Contains no identity information."""
        embed = self.factory.base(
            title=f"Account history \u00b7 {history.alias_display}",
            description=subtext(
                "Hush history for this account. Identity is not shown."
            ),
            color=Colors.WARNING if history.is_currently_banned else Colors.BRAND,
        )
        embed.add_field(
            name="Warnings",
            value=f"{history.warning_count} ({history.active_warnings} active)",
            inline=True,
        )
        embed.add_field(
            name="Bans",
            value=f"{history.temp_ban_count} temp \u00b7 {history.permanent_ban_count} perm",
            inline=True,
        )
        embed.add_field(
            name="Currently banned",
            value="Yes" if history.is_currently_banned else "No",
            inline=True,
        )
        embed.add_field(
            name="Removed confessions", value=str(history.removed_confession_count), inline=True
        )
        embed.add_field(name="Reports received", value=str(history.report_count), inline=True)
        if history.entries:
            embed.add_field(
                name="Recent actions", value="\n".join(history.entries[:8]), inline=False
            )
        return embed

    def confirm_action(
        self, *, action: str, target: str, reason: str, consequence: str
    ) -> discord.Embed:
        embed = self.factory.base(
            title=f"{action} {target}?",
            description=consequence,
            color=Colors.ERROR,
        )
        embed.add_field(name="Reason", value=reason or "Not specified", inline=False)
        embed.set_footer(text="This action is recorded in the moderation ledger.")
        return embed
