"""Ephemeral rating menu.

One button on the confession, one scale here. A rating means "how strongly did
you react to this overall" - not how moral, funny or wholesome it was.
"""

from __future__ import annotations

import discord

from app.services.rating_service import RatingService
from app.views.common import HushView, guarded, respond, runtime_of

SCALE_HINTS = {1: "Weak", None: "", 0: ""}


class RatingButton(discord.ui.Button):
    def __init__(self, value: int, *, selected: bool):
        super().__init__(
            label=str(value),
            style=discord.ButtonStyle.success if selected else discord.ButtonStyle.secondary,
            row=0,
        )
        self.value = value

    async def callback(self, interaction: discord.Interaction) -> None:
        view: "RatingView" = self.view  # type: ignore[assignment]

        async def action() -> None:
            runtime = runtime_of(interaction)
            async with runtime.session() as session:
                service = RatingService(session, runtime.settings)
                await service.rate(
                    confession_id=view.confession_id,
                    guild_id=view.guild_id,
                    voter_internal_user_id=view.internal_user_id,
                    value=self.value,
                )
                average, count = await service.summary(view.confession_id)

            embed = runtime.embeds.success(
                "Rating saved",
                f"You rated this confession **{self.value}/{view.scale_max}**.\n\n"
                f"It now averages **{average:.1f}/{view.scale_max}** "
                f"across {count} rating{'s' if count != 1 else ''}.",
            )
            embed.set_footer(text="You can change your rating at any time.")
            await respond(interaction, embed=embed, view=None, edit=True)

            # Keep the public message in step with the new average.
            if runtime.publishing is not None:
                await runtime.publishing.refresh_message(view.confession_id)

        await guarded(interaction, "rating.submit", action)


class RatingView(HushView):
    def __init__(
        self,
        *,
        confession_id: str,
        guild_id: int,
        internal_user_id: str,
        scale_min: int,
        scale_max: int,
        current: int | None = None,
    ):
        super().__init__(timeout=180)
        self.confession_id = confession_id
        self.guild_id = guild_id
        self.internal_user_id = internal_user_id
        self.scale_max = scale_max
        for value in range(scale_min, scale_max + 1):
            self.add_item(RatingButton(value, selected=value == current))

    @staticmethod
    def prompt_embed(runtime, *, current: int | None, scale_max: int) -> discord.Embed:
        embed = runtime.embeds.base(
            title="Rate this confession",
            description="How strongly did you react to this confession overall?",
        )
        if current is not None:
            embed.add_field(
                name="Your current rating",
                value=f"**{current}/{scale_max}**",
                inline=False,
            )
        embed.set_footer(text="You can change your rating at any time.")
        return embed
