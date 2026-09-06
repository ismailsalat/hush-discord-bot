"""Reporting.

A report is a signal to moderators, never an automatic removal. That is stated
to the reporter so nobody expects a confession to vanish on submit.
"""

from __future__ import annotations

import discord

from app.core.constants import ReportReason
from app.views.common import HushView, guarded, respond, runtime_of


class ReportReasonView(HushView):
    def __init__(self, *, confession_id: str, guild_id: int, internal_user_id: str):
        super().__init__(timeout=180)
        self.confession_id = confession_id
        self.guild_id = guild_id
        self.internal_user_id = internal_user_id

        self.select: discord.ui.Select = discord.ui.Select(
            placeholder="Select a reason",
            options=[
                discord.SelectOption(label=reason.label, value=reason.value)
                for reason in ReportReason
            ],
        )
        self.select.callback = self._chosen  # type: ignore[assignment]
        self.add_item(self.select)

    async def _chosen(self, interaction: discord.Interaction) -> None:
        reason = ReportReason(self.select.values[0])

        if reason is ReportReason.OTHER:
            from app.modals.confession import ReasonModal

            async def submit_with_details(inner: discord.Interaction, details: str) -> None:
                await self._file(inner, reason, details)

            await interaction.response.send_modal(
                ReasonModal(
                    title="Report confession",
                    label="What's wrong with it?",
                    placeholder="Give moderators some context...",
                    on_submit_callback=submit_with_details,
                )
            )
            return

        await guarded(
            interaction, "report.submit", lambda: self._file(interaction, reason, None)
        )

    async def _file(
        self, interaction: discord.Interaction, reason: ReportReason, details: str | None
    ) -> None:
        from app.services.moderation_service import ModerationService

        runtime = runtime_of(interaction)
        retry_after = runtime.rate_limiter.hit(
            f"report:{self.internal_user_id}", runtime.report_rule
        )
        if retry_after:
            await respond(
                interaction,
                embed=runtime.error_embeds.rate_limited(
                    "You've filed several reports recently. Please wait a little while."
                ),
                view=None,
                edit=True,
            )
            return

        async with runtime.session() as session:
            await ModerationService(session, runtime.settings).report(
                confession_id=self.confession_id,
                reporter_internal_user_id=self.internal_user_id,
                reason=reason,
                details=details,
            )

        await respond(
            interaction,
            embed=runtime.moderation_embeds.report_confirmation(),
            view=None,
            edit=True,
        )
