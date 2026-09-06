"""Moderator control surfaces.

Moderators act on an *alias*, not a person. Nothing in these views reveals who
wrote a confession - identity lookup is a separate, owner-only, always-logged
command. Every action here writes to the append-only moderation ledger and, if
configured, mirrors to the mod log channel.
"""

from __future__ import annotations

import discord

from app.core.constants import BanDuration
from app.views.common import HushView, guarded, respond, runtime_of


class ModerationPanelView(HushView):
    """Actions available against one confession."""

    def __init__(
        self,
        *,
        confession_id: str,
        guild_id: int,
        public_number: int,
        alias_display: str,
        author_internal_user_id: str,
        moderator_id: int,
        report_id: str | None = None,
    ):
        super().__init__(timeout=300)
        self.confession_id = confession_id
        self.guild_id = guild_id
        self.public_number = public_number
        self.alias_display = alias_display
        self.author_internal_user_id = author_internal_user_id
        self.moderator_id = moderator_id
        self.report_id = report_id
        if report_id is None:
            self.remove_item(self.resolve_report_button)
            self.remove_item(self.dismiss_report_button)

    async def _reason_then(self, interaction: discord.Interaction, *, title: str, callback):
        from app.modals.confession import ReasonModal

        await interaction.response.send_modal(
            ReasonModal(title=title, on_submit_callback=callback)
        )

    @discord.ui.button(
        label="Remove", emoji="\U0001f5d1", style=discord.ButtonStyle.danger, row=0
    )
    async def remove(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        async def submitted(inner: discord.Interaction, reason: str) -> None:
            from app.services.moderation_service import ModerationService

            runtime = runtime_of(inner)
            async with runtime.session() as session:
                await ModerationService(session, runtime.settings).remove_confession(
                    self.confession_id,
                    moderator_id=self.moderator_id,
                    reason=reason,
                    guild_name=inner.guild.name if inner.guild else None,
                )
            if runtime.publishing is not None:
                await runtime.publishing.withdraw_message(self.confession_id)

            await respond(
                inner,
                embed=runtime.embeds.success(
                    "Confession removed",
                    f"Confession **#{self.public_number}** was removed and the author has been "
                    "notified.",
                ),
            )
            await mirror_to_mod_log(
                inner,
                action="Confession Removed",
                alias_display=self.alias_display,
                reason=reason,
                confession_number=self.public_number,
                guild_id=self.guild_id,
            )

        await self._reason_then(
            interaction, title=f"Remove confession #{self.public_number}", callback=submitted
        )

    @discord.ui.button(
        label="Warn Author", emoji="\u26a0", style=discord.ButtonStyle.secondary, row=0
    )
    async def warn(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        async def submitted(inner: discord.Interaction, reason: str) -> None:
            from app.services.moderation_service import ModerationService

            runtime = runtime_of(inner)
            async with runtime.session() as session:
                await ModerationService(session, runtime.settings).warn(
                    internal_user_id=self.author_internal_user_id,
                    guild_id=self.guild_id,
                    moderator_id=self.moderator_id,
                    reason=reason,
                    related_confession_id=self.confession_id,
                    guild_name=inner.guild.name if inner.guild else None,
                )
            await respond(
                inner,
                embed=runtime.embeds.success(
                    "Warning issued",
                    f"{self.alias_display} has been warned. They will see the notice the next "
                    "time they use the bot, even if their DMs are closed.",
                ),
            )
            await mirror_to_mod_log(
                inner,
                action="Warning Issued",
                alias_display=self.alias_display,
                reason=reason,
                confession_number=self.public_number,
                guild_id=self.guild_id,
                punishment="Warning",
            )

        await self._reason_then(
            interaction, title=f"Warn {self.alias_display}", callback=submitted
        )

    @discord.ui.button(
        label="Ban Author", emoji="\U0001f512", style=discord.ButtonStyle.danger, row=1
    )
    async def ban(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        async def action() -> None:
            runtime = runtime_of(interaction)
            await respond(
                interaction,
                embed=runtime.embeds.warning(
                    f"Ban {self.alias_display}?",
                    "Choose how long they lose access to anonymous features. This does not "
                    "remove them from the Discord server.",
                ),
                view=BanDurationView(
                    guild_id=self.guild_id,
                    internal_user_id=self.author_internal_user_id,
                    alias_display=self.alias_display,
                    moderator_id=self.moderator_id,
                ),
            )

        await guarded(interaction, "moderation.ban_open", action)

    @discord.ui.button(
        label="Account History", emoji="\U0001f4cb", style=discord.ButtonStyle.secondary, row=1
    )
    async def history(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        async def action() -> None:
            from app.services.moderation_service import ModerationService

            runtime = runtime_of(interaction)
            async with runtime.session() as session:
                report = await ModerationService(session, runtime.settings).punishment_history(
                    self.author_internal_user_id, self.guild_id
                )
            await respond(interaction, embed=runtime.moderation_embeds.history(report))

        await guarded(interaction, "moderation.history", action)


    @discord.ui.button(
        label="Resolve Report", style=discord.ButtonStyle.success, row=2
    )
    async def resolve_report_button(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        async def action() -> None:
            if self.report_id is None:
                return
            from app.services.moderation_service import ModerationService

            runtime = runtime_of(interaction)
            async with runtime.session() as session:
                await ModerationService(session, runtime.settings).resolve_report(
                    self.report_id,
                    moderator_id=interaction.user.id,
                    dismissed=False,
                    note="resolved by moderator",
                )
            for child in self.children:
                if isinstance(child, (discord.ui.Button, discord.ui.Select)):
                    child.disabled = True
            await respond(
                interaction,
                embed=runtime.embeds.success(
                    "Report resolved",
                    f"The report for confession **#{self.public_number}** is closed.",
                ),
                view=self,
                edit=True,
            )
            await mirror_to_mod_log(
                interaction,
                action="Report Resolved",
                alias_display=self.alias_display,
                reason=None,
                confession_number=self.public_number,
                guild_id=self.guild_id,
            )

        await guarded(interaction, "moderation.resolve_report", action)

    @discord.ui.button(
        label="Dismiss Report", style=discord.ButtonStyle.secondary, row=2
    )
    async def dismiss_report_button(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        async def action() -> None:
            if self.report_id is None:
                return
            from app.services.moderation_service import ModerationService

            runtime = runtime_of(interaction)
            async with runtime.session() as session:
                await ModerationService(session, runtime.settings).resolve_report(
                    self.report_id,
                    moderator_id=interaction.user.id,
                    dismissed=True,
                    note="dismissed by moderator",
                )
            for child in self.children:
                if isinstance(child, (discord.ui.Button, discord.ui.Select)):
                    child.disabled = True
            await respond(
                interaction,
                embed=runtime.embeds.success(
                    "Report dismissed",
                    f"No moderation action was taken on confession **#{self.public_number}**.",
                ),
                view=self,
                edit=True,
            )
            await mirror_to_mod_log(
                interaction,
                action="Report Dismissed",
                alias_display=self.alias_display,
                reason=None,
                confession_number=self.public_number,
                guild_id=self.guild_id,
            )

        await guarded(interaction, "moderation.dismiss_report", action)


class BanDurationView(HushView):
    """1h / 24h / 7d / 30d / permanent, exactly as specified - no free-form input."""

    def __init__(
        self,
        *,
        guild_id: int,
        internal_user_id: str,
        alias_display: str,
        moderator_id: int,
    ):
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.internal_user_id = internal_user_id
        self.alias_display = alias_display
        self.moderator_id = moderator_id

        self.select: discord.ui.Select = discord.ui.Select(
            placeholder="Choose a duration",
            options=[
                discord.SelectOption(label=duration.label, value=duration.value)
                for duration in BanDuration
            ],
        )
        self.select.callback = self._chosen  # type: ignore[assignment]
        self.add_item(self.select)

    async def _chosen(self, interaction: discord.Interaction) -> None:
        duration = BanDuration(self.select.values[0])

        async def submitted(inner: discord.Interaction, reason: str) -> None:
            from app.services.moderation_service import ModerationService

            runtime = runtime_of(inner)
            async with runtime.session() as session:
                await ModerationService(session, runtime.settings).ban(
                    internal_user_id=self.internal_user_id,
                    guild_id=self.guild_id,
                    moderator_id=self.moderator_id,
                    duration=duration,
                    reason=reason,
                    guild_name=inner.guild.name if inner.guild else None,
                )
            await respond(
                inner,
                embed=runtime.embeds.success(
                    "Access suspended",
                    f"{self.alias_display} can no longer use "
                    f"{runtime.settings.brand_name} in this server ({duration.label}).",
                ),
            )
            await mirror_to_mod_log(
                inner,
                action="Access Suspended",
                alias_display=self.alias_display,
                reason=reason,
                guild_id=self.guild_id,
                punishment=duration.label,
            )

        from app.modals.confession import ReasonModal

        await interaction.response.send_modal(
            ReasonModal(title=f"Ban {self.alias_display}", on_submit_callback=submitted)
        )


class ReportQueueView(HushView):
    """Walk through open reports one at a time."""

    def __init__(self, *, guild_id: int, moderator_id: int, rows: list):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.moderator_id = moderator_id
        self.rows = rows

        if rows:
            self.select: discord.ui.Select = discord.ui.Select(
                placeholder="Open a reported confession",
                options=[
                    discord.SelectOption(
                        label=f"#{number} \u00b7 {reason.label}"[:100],
                        value=report_id,
                        description=preview[:100] or None,
                    )
                    for report_id, number, reason, preview in rows[:25]
                ],
            )
            self.select.callback = self._chosen  # type: ignore[assignment]
            self.add_item(self.select)

    async def _chosen(self, interaction: discord.Interaction) -> None:
        async def action() -> None:
            from app.services.confession_service import ConfessionService
            from app.services.moderation_service import ModerationService

            runtime = runtime_of(interaction)
            report_id = self.select.values[0]

            async with runtime.session() as session:
                moderation = ModerationService(session, runtime.settings)
                report = await moderation.reports.get(report_id)
                confessions = ConfessionService(session, runtime.settings)
                confession = await confessions.get(report.confession_id)
                data = await confessions.build_view(confession)

            panel = ModerationPanelView(
                confession_id=confession.id,
                guild_id=self.guild_id,
                public_number=data.public_number,
                alias_display=data.alias_display,
                author_internal_user_id=confession.internal_user_id,
                moderator_id=self.moderator_id,
                report_id=report_id,
            )
            await respond(
                interaction,
                embeds=[runtime.confession_embeds.build(data)],
                view=panel,
            )

        await guarded(interaction, "moderation.open_report", action)


async def mirror_to_mod_log(
    interaction: discord.Interaction,
    *,
    action: str,
    alias_display: str | None,
    reason: str | None,
    guild_id: int,
    confession_number: int | None = None,
    punishment: str | None = None,
) -> None:
    """Post the action to the configured mod log channel, if there is one."""
    runtime = runtime_of(interaction)
    async with runtime.session() as session:
        from app.database.repositories import GuildRepository

        settings = await GuildRepository(session).get_settings(guild_id)

    channel_id = settings.mod_log_channel_id if settings else None
    if not channel_id:
        return
    channel = interaction.client.get_channel(channel_id)
    if not isinstance(channel, discord.abc.Messageable):
        return

    embed = runtime.moderation_embeds.mod_log(
        action=action,
        alias_display=alias_display,
        moderator=f"<@{interaction.user.id}>",
        reason=reason,
        confession_number=confession_number,
        punishment=punishment,
    )
    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        pass
