"""Poll storage and vote tallying."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.database.models import Poll, PollOption, PollVote
from app.database.repositories.base import BaseRepository
from app.utils.time import utcnow


class PollRepository(BaseRepository):
    async def get(self, poll_id: str) -> Poll | None:
        result = await self.session.execute(
            select(Poll).options(selectinload(Poll.options)).where(Poll.id == poll_id)
        )
        return result.scalar_one_or_none()

    async def get_for_confession(self, confession_id: str) -> Poll | None:
        result = await self.session.execute(
            select(Poll).options(selectinload(Poll.options)).where(
                Poll.confession_id == confession_id
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        confession_id: str,
        created_by_internal_user_id: str,
        question: str,
        options: list[str],
    ) -> Poll:
        poll = Poll(
            confession_id=confession_id,
            created_by_internal_user_id=created_by_internal_user_id,
            question=question,
        )
        poll.options = [
            PollOption(label=label, position=index) for index, label in enumerate(options)
        ]
        self.session.add(poll)
        await self.session.flush()
        return poll

    async def get_vote(self, poll_id: str, voter_internal_user_id: str) -> PollVote | None:
        result = await self.session.execute(
            select(PollVote).where(
                PollVote.poll_id == poll_id,
                PollVote.voter_internal_user_id == voter_internal_user_id,
            )
        )
        return result.scalar_one_or_none()

    async def cast_vote(
        self, poll_id: str, option_id: str, voter_internal_user_id: str
    ) -> tuple[PollVote, bool]:
        """Cast or change a vote. Returns ``(vote, was_created)``."""
        existing = await self.get_vote(poll_id, voter_internal_user_id)
        if existing is not None:
            existing.option_id = option_id
            await self.session.flush()
            return existing, False

        vote = PollVote(
            poll_id=poll_id, option_id=option_id, voter_internal_user_id=voter_internal_user_id
        )
        self.session.add(vote)
        await self.session.flush()
        return vote, True

    async def tally(self, poll_id: str) -> dict[str, int]:
        """``{option_id: votes}`` including options with zero votes."""
        poll = await self.get(poll_id)
        counts = {option.id: 0 for option in poll.options} if poll else {}
        result = await self.session.execute(
            select(PollVote.option_id, func.count(PollVote.id))
            .where(PollVote.poll_id == poll_id)
            .group_by(PollVote.option_id)
        )
        for option_id, count in result.all():
            counts[option_id] = int(count)
        return counts

    async def close(self, poll_id: str) -> None:
        poll = await self.get(poll_id)
        if poll is not None:
            poll.closed_at = utcnow()
            await self.session.flush()

    async def list_votes_for_guild_polls(self, confession_ids: list[str]) -> list[PollVote]:
        if not confession_ids:
            return []
        result = await self.session.execute(
            select(PollVote).join(Poll, Poll.id == PollVote.poll_id).where(
                Poll.confession_id.in_(confession_ids)
            )
        )
        return list(result.scalars().all())
