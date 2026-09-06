"""Optional polls, attached to a confession after it has been posted."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConfessionNotFoundError,
    FeatureDisabledError,
    NotConfessionAuthorError,
    PollAlreadyExistsError,
    PollNotFoundError,
)
from app.database.repositories import ConfessionRepository, GuildRepository, PollRepository
from app.services.dto import PollOptionResult, PollView
from app.utils.validators import validate_poll


class PollService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.polls = PollRepository(session)
        self.confessions = ConfessionRepository(session)
        self.guilds = GuildRepository(session)

    async def create(
        self, *, confession_id: str, internal_user_id: str, question: str, options: list[str]
    ) -> PollView:
        """Only the confession's author may attach a poll, and only one."""
        confession = await self.confessions.get_by_id(confession_id)
        if confession is None or confession.is_deleted:
            raise ConfessionNotFoundError()

        settings = await self.guilds.get_settings(confession.guild_id)
        if settings is not None and not settings.polls_enabled:
            raise FeatureDisabledError(user_message="Polls are turned off in this server.")

        if confession.internal_user_id != internal_user_id:
            raise NotConfessionAuthorError(
                "only the author may add a poll",
                user_message="Only the person who posted this confession can add a poll to it.",
            )
        if await self.polls.get_for_confession(confession_id) is not None:
            raise PollAlreadyExistsError()

        clean_question, clean_options = validate_poll(question, options)
        poll = await self.polls.create(
            confession_id=confession_id,
            created_by_internal_user_id=internal_user_id,
            question=clean_question,
            options=clean_options,
        )
        return await self.build_view(poll.id)

    async def vote(
        self, *, poll_id: str, option_id: str, voter_internal_user_id: str
    ) -> PollView:
        poll = await self.polls.get(poll_id)
        if poll is None or not poll.is_open:
            raise PollNotFoundError()
        if option_id not in {option.id for option in poll.options}:
            raise PollNotFoundError()

        await self.polls.cast_vote(poll_id, option_id, voter_internal_user_id)
        return await self.build_view(poll_id, voter_internal_user_id)

    async def build_view(self, poll_id: str, voter_internal_user_id: str | None = None) -> PollView:
        poll = await self.polls.get(poll_id)
        if poll is None:
            raise PollNotFoundError()

        tally = await self.polls.tally(poll_id)
        total = sum(tally.values())
        options = [
            PollOptionResult(
                option_id=option.id,
                label=option.label,
                votes=tally.get(option.id, 0),
                percentage=(tally.get(option.id, 0) / total * 100) if total else 0.0,
            )
            for option in poll.options
        ]

        voted_option_id = None
        if voter_internal_user_id:
            vote = await self.polls.get_vote(poll_id, voter_internal_user_id)
            voted_option_id = vote.option_id if vote else None

        return PollView(
            poll_id=poll.id,
            confession_id=poll.confession_id,
            question=poll.question,
            options=options,
            total_votes=total,
            is_open=poll.is_open,
            voted_option_id=voted_option_id,
        )

    async def get_for_confession(self, confession_id: str) -> PollView | None:
        poll = await self.polls.get_for_confession(confession_id)
        return await self.build_view(poll.id) if poll else None

    async def locate(self, poll_id: str) -> tuple[str, int]:
        """``(confession_id, guild_id)`` for a poll - what a vote callback needs."""
        poll = await self.polls.get(poll_id)
        if poll is None:
            raise PollNotFoundError()
        confession = await self.confessions.get_by_id(poll.confession_id)
        if confession is None:
            raise PollNotFoundError()
        return confession.id, confession.guild_id
