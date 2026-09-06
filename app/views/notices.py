"""Acknowledgement view for replayed moderation notices."""

from __future__ import annotations

import discord

from app.security.identifiers import build_custom_id
from app.services.notification_service import NotificationService
from app.views.common import PersistentView, guarded, respond, runtime_of


class NoticeAcknowledgeButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"cf:ack:(?P<nid>ntf_[0-9a-f]+)",
):
    """Persistent so an acknowledgement still works after a restart."""

    def __init__(self, notification_id: str):
        self.notification_id = notification_id
        super().__init__(
            discord.ui.Button(
                label="Acknowledge",
                style=discord.ButtonStyle.primary,
                custom_id=build_custom_id("ack", notification_id),
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):  # noqa: D102
        return cls(match["nid"])

    async def callback(self, interaction: discord.Interaction) -> None:
        async def action() -> None:
            runtime = runtime_of(interaction)
            async with runtime.session() as session:
                await NotificationService(session).acknowledge(self.notification_id)
                from app.services.moderation_service import ModerationService

                notification = await NotificationService(session).notifications.get(
                    self.notification_id
                )
                warning_id = (notification.payload or {}).get("warning_id") if notification else None
                if warning_id:
                    await ModerationService(session, runtime.settings).acknowledge_warning(
                        warning_id
                    )

            await respond(
                interaction,
                embed=runtime.embeds.success(
                    "Thank you", "This notice has been acknowledged. You can continue as normal."
                ),
                view=None,
                edit=True,
            )

        await guarded(interaction, "notice.acknowledge", action)


class NoticeAcknowledgeView(PersistentView):
    def __init__(self, notification_id: str):
        super().__init__()
        self.add_item(NoticeAcknowledgeButton(notification_id))


class ContinueView(PersistentView):
    """Shown when a DM could not be delivered - a simple dismissal."""

    @discord.ui.button(
        label="Continue", style=discord.ButtonStyle.secondary, custom_id="cf:continue"
    )
    async def proceed(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.edit_message(view=None)
