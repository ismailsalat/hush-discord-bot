"""Poll voting.

Poll buttons are persistent and encode the poll id plus the option index, so a
poll attached to a month-old confession still works after a restart.
"""

from __future__ import annotations

import discord

from app.core.exceptions import PollNotFoundError
from app.views.common import PersistentView, guarded, respond, runtime_of


class PollVoteButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"cf:pv:(?P<pid>pol_[0-9a-f]{4,32}):(?P<idx>\d)",
):
    def __init__(self, poll_id: str, index: int, label: str = ""):
        self.poll_id = poll_id
        self.index = index
        super().__init__(
            discord.ui.Button(
                label=(label or f"Option {index + 1}")[:80],
                style=discord.ButtonStyle.secondary,
                custom_id=f"cf:pv:{poll_id}:{index}",
                row=1,
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):  # noqa: D102
        return cls(match["pid"], int(match["idx"]), item.label or "")

    async def callback(self, interaction: discord.Interaction) -> None:
        async def action() -> None:
            from app.services.poll_service import PollService
            from app.views.gate import ensure_ready

            runtime = runtime_of(interaction)
            async with runtime.session() as session:
                confession_id, guild_id = await PollService(session).locate(self.poll_id)

            actor = await ensure_ready(interaction, guild_id)
            if actor is None:
                return

            async with runtime.session() as session:
                service = PollService(session)
                # The button carries the option's position, not its id, so the
                # custom id stays short and stable. Resolve it here.
                current = await service.build_view(self.poll_id, actor.internal_id)
                if self.index >= len(current.options):
                    raise PollNotFoundError()
                view_data = await service.vote(
                    poll_id=self.poll_id,
                    option_id=current.options[self.index].option_id,
                    voter_internal_user_id=actor.internal_id,
                )

            embed = runtime.embeds.success(
                "Vote recorded",
                f"You voted for **{view_data.options[self.index].label}**.",
            )
            embed.set_footer(text="You can change your vote at any time.")
            await respond(interaction, embed=embed)

            if runtime.publishing is not None:
                await runtime.publishing.refresh_message(confession_id)

        await guarded(interaction, "poll.vote", action)


class PollView(PersistentView):
    def __init__(self, poll_id: str, option_labels: list[str]):
        super().__init__()
        for index, label in enumerate(option_labels[:4]):
            self.add_item(PollVoteButton(poll_id, index, label))


PERSISTENT_ITEMS = (PollVoteButton,)
