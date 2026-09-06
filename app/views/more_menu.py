"""The ``More`` menu.

Secondary actions live here so the public message keeps only four buttons.
Which options appear depends on who is clicking and what the server has
enabled - authors get update/poll/delete, everyone else gets bookmark/report.
"""

from __future__ import annotations

import discord

from app.services.dto import ConfessionView
from app.views.common import HushView, guarded, respond, runtime_of


class MoreMenuView(HushView):
    def __init__(
        self,
        *,
        confession_id: str,
        guild_id: int,
        internal_user_id: str,
        is_author: bool,
        view_data: ConfessionView,
        settings=None,
    ):
        super().__init__(timeout=180)
        self.confession_id = confession_id
        self.guild_id = guild_id
        self.internal_user_id = internal_user_id
        self.is_author = is_author
        self.view_data = view_data
        self.settings = settings

        enabled = lambda name: settings is None or getattr(settings, name, True)  # noqa: E731

        if enabled("bookmarks_enabled"):
            self.add_item(_BookmarkButton())
        self.add_item(_ReportButton())

        if view_data.parent_confession_id:
            self.add_item(_ViewOriginalButton())
        if view_data.update_numbers:
            self.add_item(_ViewUpdatesButton())

        if is_author:
            if enabled("updates_enabled"):
                self.add_item(_PostUpdateButton())
            if enabled("polls_enabled") and not view_data.has_poll:
                self.add_item(_AddPollButton())
            self.add_item(_DeleteOwnButton())


class _MenuButton(discord.ui.Button):
    def __init__(self, label: str, emoji: str, *, style=discord.ButtonStyle.secondary, row=None):
        super().__init__(label=label, emoji=emoji, style=style, row=row)

    @property
    def menu(self) -> MoreMenuView:
        return self.view  # type: ignore[return-value]


class _BookmarkButton(_MenuButton):
    def __init__(self):
        super().__init__("Bookmark", "\U0001f516")

    async def callback(self, interaction: discord.Interaction) -> None:
        async def action() -> None:
            from app.services.bookmark_service import BookmarkService

            runtime = runtime_of(interaction)
            async with runtime.session() as session:
                saved = await BookmarkService(session).toggle(
                    internal_user_id=self.menu.internal_user_id,
                    confession_id=self.menu.confession_id,
                )
            if saved:
                embed = runtime.embeds.info(
                    "\U0001f516 Saved",
                    f"Confession **#{self.menu.view_data.public_number}** was added to your "
                    "bookmarks.",
                )
                embed.set_footer(text="Only you can see your bookmarks.")
            else:
                embed = runtime.embeds.base(
                    title="Bookmark removed",
                    description=f"Confession **#{self.menu.view_data.public_number}** is no "
                    "longer saved.",
                )
            await respond(interaction, embed=embed, view=None, edit=True)

        await guarded(interaction, "more.bookmark", action)


class _ReportButton(_MenuButton):
    def __init__(self):
        super().__init__("Report", "\U0001f6a9", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction) -> None:
        async def action() -> None:
            from app.views.report import ReportReasonView

            runtime = runtime_of(interaction)
            await respond(
                interaction,
                embed=runtime.moderation_embeds.report_form_intro(),
                view=ReportReasonView(
                    confession_id=self.menu.confession_id,
                    guild_id=self.menu.guild_id,
                    internal_user_id=self.menu.internal_user_id,
                ),
                edit=True,
            )

        await guarded(interaction, "more.report", action)


class _PostUpdateButton(_MenuButton):
    def __init__(self):
        super().__init__("Post Update", "\u21a9", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction) -> None:
        from app.modals.confession import ConfessionModal

        runtime = runtime_of(interaction)
        limit = getattr(
            self.menu.settings,
            "confession_character_limit",
            runtime.settings.default_confession_limit,
        )
        await interaction.response.send_modal(
            ConfessionModal(
                guild_id=self.menu.guild_id,
                limit=limit,
                parent_confession_id=self.menu.confession_id,
                brand=runtime.settings.brand_name,
            )
        )


class _AddPollButton(_MenuButton):
    def __init__(self):
        super().__init__("Add Poll", "\U0001f4ca")

    async def callback(self, interaction: discord.Interaction) -> None:
        from app.modals.confession import PollModal

        await interaction.response.send_modal(
            PollModal(
                confession_id=self.menu.confession_id,
                guild_id=self.menu.guild_id,
                internal_user_id=self.menu.internal_user_id,
            )
        )


class _DeleteOwnButton(_MenuButton):
    def __init__(self):
        super().__init__("Delete", "\U0001f5d1", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction) -> None:
        async def action() -> None:
            from app.views.common import ConfirmView

            runtime = runtime_of(interaction)
            confirm = ConfirmView(confirm_label="Delete")
            await respond(
                interaction,
                embed=runtime.embeds.warning(
                    "Delete this confession?",
                    f"Confession **#{self.menu.view_data.public_number}** will be removed from "
                    "the channel. This cannot be undone from your side.",
                ),
                view=confirm,
                edit=True,
            )
            await confirm.wait()
            if not confirm.value or confirm.interaction is None:
                return

            from app.services.confession_service import ConfessionService

            async with runtime.session() as session:
                await ConfessionService(session, runtime.settings).remove(
                    self.menu.confession_id, moderator_id=None, reason="Deleted by author"
                )
            if runtime.publishing is not None:
                await runtime.publishing.withdraw_message(self.menu.confession_id)

            await confirm.interaction.response.edit_message(
                embed=runtime.embeds.success(
                    "Confession deleted", "Your confession has been removed."
                ),
                view=None,
            )

        await guarded(interaction, "more.delete", action)


class _ViewOriginalButton(_MenuButton):
    def __init__(self):
        super().__init__("View Original", "\U0001f4dc")

    async def callback(self, interaction: discord.Interaction) -> None:
        async def action() -> None:
            from app.services.confession_service import ConfessionService

            runtime = runtime_of(interaction)
            async with runtime.session() as session:
                service = ConfessionService(session, runtime.settings)
                parent = await service.get_visible(self.menu.view_data.parent_confession_id)
                data = await service.build_view(parent)
            await respond(
                interaction, embed=runtime.confession_embeds.build(data), view=None, edit=True
            )

        await guarded(interaction, "more.view_original", action)


class _ViewUpdatesButton(_MenuButton):
    def __init__(self):
        super().__init__("View Updates", "\U0001f195")

    async def callback(self, interaction: discord.Interaction) -> None:
        async def action() -> None:
            from app.services.confession_service import ConfessionService

            runtime = runtime_of(interaction)
            async with runtime.session() as session:
                chain = await ConfessionService(session, runtime.settings).chain_summary(
                    self.menu.confession_id
                )

            lines = [
                f"**#{number}** \u00b7 {preview}" + ("  \u2190 you are here" if current else "")
                for number, preview, current in chain
            ]
            embed = runtime.embeds.base(
                title="This confession's story",
                description="\n".join(lines) or "No updates yet.",
            )
            await respond(interaction, embed=embed, view=None, edit=True)

        await guarded(interaction, "more.view_updates", action)
