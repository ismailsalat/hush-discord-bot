"""Text entry modals for confessions and updates."""

from __future__ import annotations

import discord

from app.views.common import guarded, respond, runtime_of


class ConfessionModal(discord.ui.Modal):
    """Where the confession is actually typed.

    Discord caps a modal input at 4000 characters; the server-side limit is
    enforced again in the service layer, so a lowered guild limit is still
    respected even though the modal itself cannot go below it.
    """

    def __init__(
        self,
        *,
        guild_id: int,
        limit: int,
        parent_confession_id: str | None = None,
        prefill: str | None = None,
        brand: str = "Hush",
    ):
        title = "Post an update" if parent_confession_id else "New confession"
        super().__init__(title=title, timeout=900)
        self.guild_id = guild_id
        self.limit = limit
        self.parent_confession_id = parent_confession_id

        self.content: discord.ui.TextInput = discord.ui.TextInput(
            label="Your confession",
            style=discord.TextStyle.paragraph,
            placeholder="Type anything you want to say anonymously...",
            max_length=min(limit, 4000),
            required=True,
            default=prefill,
        )
        self.add_item(self.content)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        async def action() -> None:
            from app.views.submission import PreviewView

            runtime = runtime_of(interaction)
            text = str(self.content.value)

            await respond(
                interaction,
                embed=runtime.confession_embeds.preview(text, self.limit),
                view=PreviewView(
                    guild_id=self.guild_id,
                    content=text,
                    limit=self.limit,
                    parent_confession_id=self.parent_confession_id,
                ),
            )

        await guarded(interaction, "modal.confession", action)

    async def on_error(
        self, interaction: discord.Interaction, error: Exception
    ) -> None:  # pragma: no cover
        from app.views.common import handle_error

        await handle_error(interaction, error, operation="modal.confession")


class PollModal(discord.ui.Modal, title="Add a poll"):
    """Polls are added after posting, never during. Two to four options."""

    question: discord.ui.TextInput = discord.ui.TextInput(
        label="Question",
        placeholder="What do you want to ask?",
        max_length=200,
        required=True,
    )
    options: discord.ui.TextInput = discord.ui.TextInput(
        label="Options (one per line, 2-4)",
        style=discord.TextStyle.paragraph,
        placeholder="Yes\nNo\nMaybe",
        max_length=400,
        required=True,
    )

    def __init__(self, *, confession_id: str, guild_id: int, internal_user_id: str):
        super().__init__(timeout=600)
        self.confession_id = confession_id
        self.guild_id = guild_id
        self.internal_user_id = internal_user_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        async def action() -> None:
            from app.services.poll_service import PollService

            runtime = runtime_of(interaction)
            labels = [line.strip() for line in str(self.options.value).splitlines() if line.strip()]

            async with runtime.session() as session:
                await PollService(session).create(
                    confession_id=self.confession_id,
                    internal_user_id=self.internal_user_id,
                    question=str(self.question.value),
                    options=labels,
                )

            await respond(
                interaction,
                embed=runtime.embeds.success(
                    "Poll added", "Your poll is now attached to the confession."
                ),
            )
            if runtime.publishing is not None:
                await runtime.publishing.refresh_message(self.confession_id)

        await guarded(interaction, "modal.poll", action)

    async def on_error(
        self, interaction: discord.Interaction, error: Exception
    ) -> None:  # pragma: no cover
        from app.views.common import handle_error

        await handle_error(interaction, error, operation="modal.poll")


class ReasonModal(discord.ui.Modal):
    """Collects a free-text reason for a moderator action or a report."""

    def __init__(
        self,
        *,
        title: str,
        label: str = "Reason",
        placeholder: str = "Explain briefly...",
        required: bool = True,
        on_submit_callback=None,
    ):
        super().__init__(title=title, timeout=600)
        self._callback = on_submit_callback
        self.reason: discord.ui.TextInput = discord.ui.TextInput(
            label=label,
            style=discord.TextStyle.paragraph,
            placeholder=placeholder,
            max_length=500,
            required=required,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        async def action() -> None:
            if self._callback is not None:
                await self._callback(interaction, str(self.reason.value).strip())

        await guarded(interaction, "modal.reason", action)

    async def on_error(
        self, interaction: discord.Interaction, error: Exception
    ) -> None:  # pragma: no cover
        from app.views.common import handle_error

        await handle_error(interaction, error, operation="modal.reason")
