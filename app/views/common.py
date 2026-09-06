"""Shared view and component plumbing.

Everything user-facing routes through here so that:

* no button can silently fail - every failure produces a visible embed
* double clicks are absorbed rather than duplicated
* long operations are deferred before Discord's 3 second deadline expires
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable

import discord

from app.core.exceptions import HushError
from app.logging.error_ids import report_exception

if TYPE_CHECKING:  # pragma: no cover
    from app.core.runtime import Runtime


_UNSET = object()


def runtime_of(interaction: discord.Interaction) -> "Runtime":
    """Fetch the runtime from the bot attached to an interaction."""
    return interaction.client.runtime  # type: ignore[attr-defined]


async def respond(
    interaction: discord.Interaction,
    *,
    embed: discord.Embed | None = None,
    embeds: list[discord.Embed] | None = None,
    view: discord.ui.View | None | object = _UNSET,
    ephemeral: bool = True,
    edit: bool = False,
) -> None:
    """Reply safely whatever state the interaction is in.

    Discord raises if you respond twice or respond after deferring, so this
    picks the correct call rather than making every call site think about it.
    """
    kwargs: dict[str, Any] = {}
    if embed is not None:
        kwargs["embed"] = embed
    if embeds is not None:
        kwargs["embeds"] = embeds
    # Explicit ``view=None`` means "remove the existing components" when
    # editing.  Omitting ``view`` means "leave the existing view unchanged".
    if view is not _UNSET:
        kwargs["view"] = view

    try:
        if edit and interaction.response.is_done():
            await interaction.edit_original_response(**kwargs)
        elif edit:
            await interaction.response.edit_message(**kwargs)
        elif interaction.response.is_done():
            await interaction.followup.send(ephemeral=ephemeral, **kwargs)
        else:
            await interaction.response.send_message(ephemeral=ephemeral, **kwargs)
    except discord.NotFound:
        # The interaction token expired; nothing more can be sent.
        pass
    except discord.HTTPException:
        raise


async def handle_error(
    interaction: discord.Interaction, exc: BaseException, *, operation: str
) -> None:
    """Turn any exception into a friendly, ephemeral embed.

    Known domain errors show their own wording. Anything unexpected gets a short
    error id that is also written to the application log with a stack trace.
    """
    runtime = runtime_of(interaction)

    if isinstance(exc, HushError):
        embed = runtime.error_embeds.from_exception(exc)
    else:
        report = report_exception(
            exc,
            operation=operation,
            guild_id=interaction.guild_id,
            interaction=str(interaction.type),
        )
        embed = runtime.error_embeds.from_report(report)

    try:
        await respond(interaction, embed=embed, ephemeral=True)
    except Exception:  # pragma: no cover - the interaction is already gone
        pass


async def guarded(
    interaction: discord.Interaction,
    operation: str,
    action: Callable[[], Awaitable[None]],
) -> None:
    """Run a component callback with duplicate protection and error handling."""
    runtime = runtime_of(interaction)

    if runtime.interaction_guard.is_duplicate(interaction.id):
        return

    retry_after = runtime.rate_limiter.hit(
        f"interaction:{interaction.user.id}", runtime.interaction_rule
    )
    if retry_after:
        await respond(
            interaction,
            embed=runtime.error_embeds.rate_limited(
                "You're clicking a little too quickly. Give it a moment."
            ),
        )
        return

    try:
        await action()
    except Exception as exc:
        await handle_error(interaction, exc, operation=operation)


class HushView(discord.ui.View):
    """Base for ephemeral, per-interaction views."""

    def __init__(self, *, timeout: float | None = 300):
        super().__init__(timeout=timeout)

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item
    ) -> None:
        await handle_error(interaction, error, operation=f"view.{type(item).__name__}")

    async def on_timeout(self) -> None:
        for child in self.children:
            if isinstance(child, (discord.ui.Button, discord.ui.Select)):
                child.disabled = True


class PersistentView(discord.ui.View):
    """Base for views attached to messages that outlive the process."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item
    ) -> None:
        await handle_error(interaction, error, operation=f"persistent.{type(item).__name__}")


class ConfirmView(HushView):
    """Two-button confirmation used before destructive moderator actions."""

    def __init__(self, *, confirm_label: str = "Confirm", danger: bool = True):
        super().__init__(timeout=120)
        self.value: bool | None = None
        self.interaction: discord.Interaction | None = None
        self.confirm.label = confirm_label
        self.confirm.style = (
            discord.ButtonStyle.danger if danger else discord.ButtonStyle.success
        )

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.value = True
        self.interaction = interaction
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self.value = False
        self.interaction = interaction
        await interaction.response.edit_message(
            embed=runtime_of(interaction).error_embeds.generic(
                "Cancelled", "No action was taken."
            ),
            view=None,
        )
        self.stop()
