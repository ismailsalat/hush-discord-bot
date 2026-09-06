"""Preview, edit and post - the last step before a confession goes public."""

from __future__ import annotations

import discord

from app.views.common import HushView, guarded, respond, runtime_of


class PreviewView(HushView):
    """``[Post] [Edit] [Cancel]``.

    Nothing is written to the confession channel until Post is pressed, and if
    posting fails the text is saved as a draft rather than lost.
    """

    def __init__(
        self,
        *,
        guild_id: int,
        content: str,
        limit: int,
        parent_confession_id: str | None = None,
    ):
        super().__init__(timeout=900)
        self.guild_id = guild_id
        self.content = content
        self.limit = limit
        self.parent_confession_id = parent_confession_id

    @discord.ui.button(label="Post", emoji="\u2705", style=discord.ButtonStyle.success)
    async def post(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        async def action() -> None:
            from app.views.gate import ensure_ready

            runtime = runtime_of(interaction)
            actor = await ensure_ready(
                interaction, self.guild_id, require_agreement=True, defer=True
            )
            if actor is None:
                return

            # One submission at a time per user, so a double click cannot
            # produce two confessions.
            if not runtime.in_flight.acquire(f"submit:{actor.internal_id}"):
                await respond(
                    interaction,
                    embed=runtime.error_embeds.rate_limited(
                        "Your previous confession is still being posted. Hang on a second."
                    ),
                )
                return

            try:
                retry_after = runtime.rate_limiter.hit(
                    f"confess:{actor.internal_id}", runtime.confession_rule
                )
                if retry_after:
                    await respond(
                        interaction,
                        embed=runtime.error_embeds.rate_limited(
                            "You've posted a lot recently. Try again in "
                            f"{int(retry_after // 60) + 1} minute(s)."
                        ),
                    )
                    return

                assert runtime.publishing is not None
                result = await runtime.publishing.submit(
                    internal_user_id=actor.internal_id,
                    guild_id=self.guild_id,
                    content=self.content,
                    parent_confession_id=self.parent_confession_id,
                )
            finally:
                runtime.in_flight.release(f"submit:{actor.internal_id}")

            if result.ok and result.view is not None:
                embed = runtime.confession_embeds.posted(result.view)
                await respond(interaction, embed=embed, view=None, edit=True)
            else:
                embed = (
                    runtime.error_embeds.from_exception(result.error)
                    if result.error is not None
                    else runtime.error_embeds.posting_failed(
                        error_id=result.error_report.error_id if result.error_report else None
                    )
                )
                await respond(
                    interaction,
                    embed=embed,
                    view=DraftRetryView(
                        guild_id=self.guild_id,
                        content=self.content,
                        limit=self.limit,
                        parent_confession_id=self.parent_confession_id,
                    ),
                    edit=True,
                )

        await guarded(interaction, "submission.post", action)

    @discord.ui.button(label="Edit", emoji="\u270f\ufe0f", style=discord.ButtonStyle.secondary)
    async def edit(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        from app.modals.confession import ConfessionModal

        await interaction.response.send_modal(
            ConfessionModal(
                guild_id=self.guild_id,
                limit=self.limit,
                parent_confession_id=self.parent_confession_id,
                prefill=self.content,
            )
        )

    @discord.ui.button(label="Cancel", emoji="\u274c", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        async def action() -> None:
            runtime = runtime_of(interaction)
            await respond(
                interaction,
                embed=runtime.error_embeds.generic(
                    "Cancelled", "Your confession was not posted and has been discarded."
                ),
                view=None,
                edit=True,
            )

        await guarded(interaction, "submission.cancel", action)


class DraftRetryView(HushView):
    """Offered after a failed post so the text is never lost."""

    def __init__(
        self,
        *,
        guild_id: int,
        content: str,
        limit: int,
        parent_confession_id: str | None = None,
    ):
        super().__init__(timeout=1800)
        self.guild_id = guild_id
        self.content = content
        self.limit = limit
        self.parent_confession_id = parent_confession_id

    @discord.ui.button(label="Try Again", emoji="\U0001f504", style=discord.ButtonStyle.primary)
    async def retry(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        async def action() -> None:
            runtime = runtime_of(interaction)
            await respond(
                interaction,
                embed=runtime.confession_embeds.preview(self.content, self.limit),
                view=PreviewView(
                    guild_id=self.guild_id,
                    content=self.content,
                    limit=self.limit,
                    parent_confession_id=self.parent_confession_id,
                ),
                edit=True,
            )

        await guarded(interaction, "draft.retry", action)

    @discord.ui.button(label="Discard", style=discord.ButtonStyle.secondary)
    async def discard(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        async def action() -> None:
            from app.services.user_service import UserService

            runtime = runtime_of(interaction)
            async with runtime.session() as session:
                user = await UserService(session, runtime.settings).resolve(
                    interaction.user.id, self.guild_id
                )
                from app.database.repositories import DraftRepository

                await DraftRepository(session).delete_for_user(user.internal_id, self.guild_id)
            await respond(
                interaction,
                embed=runtime.error_embeds.generic("Discarded", "Your draft has been deleted."),
                view=None,
                edit=True,
            )

        await guarded(interaction, "draft.discard", action)
