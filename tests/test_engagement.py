"""Ratings, follows, bookmarks and polls."""

from __future__ import annotations

import pytest

from app.core.exceptions import PollNotFoundError
from app.database.repositories import GuildRepository
from app.services.bookmark_service import BookmarkService
from app.services.follow_service import FollowService
from app.services.poll_service import PollService
from app.services.rating_service import RatingService
from tests.conftest import GUILD_ID


class TestRatings:
    async def test_rating_is_stored(self, session, settings, factory):
        confession = await factory.confession()
        voter, _ = await factory.member()
        service = RatingService(session, settings)

        await service.rate(
            confession_id=confession.id,
            guild_id=GUILD_ID,
            voter_internal_user_id=voter.id,
            value=4,
        )
        average, count = await service.summary(confession.id)
        assert (average, count) == (4.0, 1)

    async def test_changing_a_rating_updates_in_place(self, session, settings, factory):
        """One person, one rating - changing it must not inflate the count."""
        confession = await factory.confession()
        voter, _ = await factory.member()
        service = RatingService(session, settings)

        await service.rate(
            confession_id=confession.id, guild_id=GUILD_ID,
            voter_internal_user_id=voter.id, value=2,
        )
        await service.rate(
            confession_id=confession.id, guild_id=GUILD_ID,
            voter_internal_user_id=voter.id, value=5,
        )
        average, count = await service.summary(confession.id)
        assert count == 1
        assert average == 5.0

    async def test_average_across_voters(self, session, settings, factory):
        confession = await factory.confession()
        service = RatingService(session, settings)
        for value in (1, 2, 3, 4, 5):
            voter, _ = await factory.member()
            await service.rate(
                confession_id=confession.id, guild_id=GUILD_ID,
                voter_internal_user_id=voter.id, value=value,
            )
        average, count = await service.summary(confession.id)
        assert count == 5
        assert average == 3.0

    @pytest.mark.parametrize("value", [0, 6, -1, 100])
    async def test_out_of_scale_values_are_rejected(
        self, session, settings, factory, value
    ):
        confession = await factory.confession()
        voter, _ = await factory.member()
        with pytest.raises(Exception):
            await RatingService(session, settings).rate(
                confession_id=confession.id, guild_id=GUILD_ID,
                voter_internal_user_id=voter.id, value=value,
            )

    async def test_existing_rating_is_readable(self, session, settings, factory):
        confession = await factory.confession()
        voter, _ = await factory.member()
        service = RatingService(session, settings)
        assert await service.get_existing_value(confession.id, voter.id) is None
        await service.rate(
            confession_id=confession.id, guild_id=GUILD_ID,
            voter_internal_user_id=voter.id, value=3,
        )
        assert await service.get_existing_value(confession.id, voter.id) == 3


class TestFollows:
    async def test_follow_and_unfollow(self, session, factory):
        _author, alias = await factory.member()
        follower, _ = await factory.member()
        service = FollowService(session)

        assert await service.toggle(
            follower_internal_user_id=follower.id, alias_id=alias.id
        ) is True
        assert await service.follower_count(alias.id) == 1

        assert await service.toggle(
            follower_internal_user_id=follower.id, alias_id=alias.id
        ) is False
        assert await service.follower_count(alias.id) == 0

    async def test_following_twice_does_not_duplicate(self, session, factory):
        _author, alias = await factory.member()
        follower, _ = await factory.member()
        service = FollowService(session)
        await service.follow(follower_internal_user_id=follower.id, alias_id=alias.id)
        with pytest.raises(Exception):
            await service.follow(follower_internal_user_id=follower.id, alias_id=alias.id)
        assert await service.follower_count(alias.id) == 1

    async def test_disabled_feature_blocks_following(self, session, factory):
        _author, alias = await factory.member()
        follower, _ = await factory.member()
        await GuildRepository(session).update_settings(GUILD_ID, followers_enabled=False)
        with pytest.raises(Exception):
            await FollowService(session).follow(
                follower_internal_user_id=follower.id, alias_id=alias.id
            )


class TestBookmarks:
    async def test_bookmark_toggles(self, session, factory):
        confession = await factory.confession()
        user, _ = await factory.member()
        service = BookmarkService(session)

        assert await service.toggle(
            internal_user_id=user.id, confession_id=confession.id
        ) is True
        assert await service.is_bookmarked(user.id, confession.id)

        assert await service.toggle(
            internal_user_id=user.id, confession_id=confession.id
        ) is False
        assert not await service.is_bookmarked(user.id, confession.id)

    async def test_bookmarks_are_private_to_each_user(self, session, factory):
        confession = await factory.confession()
        one, _ = await factory.member()
        two, _ = await factory.member()
        service = BookmarkService(session)

        await service.toggle(internal_user_id=one.id, confession_id=confession.id)
        assert await service.is_bookmarked(one.id, confession.id)
        assert not await service.is_bookmarked(two.id, confession.id)
        assert await service.list_rows(two.id) == []


class TestPolls:
    async def test_poll_is_added_after_posting(self, session, factory):
        confession = await factory.confession()
        poll = await PollService(session).create(
            confession_id=confession.id,
            internal_user_id=confession.internal_user_id,
            question="Was I wrong?",
            options=["Yes", "No"],
        )
        assert poll.question == "Was I wrong?"
        assert len(poll.options) == 2

    @pytest.mark.parametrize("labels", [["only one"], ["a", "b", "c", "d", "e"], []])
    async def test_option_count_is_enforced(self, session, factory, labels):
        confession = await factory.confession()
        with pytest.raises(Exception):
            await PollService(session).create(
                confession_id=confession.id,
                internal_user_id=confession.internal_user_id,
                question="?",
                options=labels,
            )

    async def test_one_poll_per_confession(self, session, factory):
        confession = await factory.confession()
        service = PollService(session)
        await service.create(
            confession_id=confession.id,
            internal_user_id=confession.internal_user_id,
            question="First?",
            options=["a", "b"],
        )
        with pytest.raises(Exception):
            await service.create(
                confession_id=confession.id,
                internal_user_id=confession.internal_user_id,
                question="Second?",
                options=["a", "b"],
            )

    async def test_changing_a_vote_does_not_double_count(self, session, factory):
        confession = await factory.confession()
        service = PollService(session)
        poll = await service.create(
            confession_id=confession.id,
            internal_user_id=confession.internal_user_id,
            question="Which?",
            options=["Left", "Right"],
        )
        voter, _ = await factory.member()
        left, right = poll.options[0].option_id, poll.options[1].option_id

        await service.vote(
            poll_id=poll.poll_id, option_id=left, voter_internal_user_id=voter.id
        )
        await service.vote(
            poll_id=poll.poll_id, option_id=right, voter_internal_user_id=voter.id
        )

        view = await service.build_view(poll.poll_id, voter.id)
        assert view.total_votes == 1
        assert view.options[0].votes == 0
        assert view.options[1].votes == 1
        assert view.voted_option_id == view.options[1].option_id

    async def test_only_the_author_may_add_a_poll(self, session, factory):
        confession = await factory.confession()
        stranger, _ = await factory.member()
        with pytest.raises(Exception):
            await PollService(session).create(
                confession_id=confession.id,
                internal_user_id=stranger.id,
                question="Mine now?",
                options=["a", "b"],
            )

    async def test_missing_poll_raises(self, session):
        with pytest.raises(PollNotFoundError):
            await PollService(session).build_view("pol_missing", None)
