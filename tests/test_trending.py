"""Trending scoring and hall of fame."""

from __future__ import annotations

from app.services.rating_service import RatingService
from app.services.trending_service import TrendingService, TrendingWeights, score_confession
from tests.conftest import GUILD_ID


class TestScoring:
    def test_engagement_beats_silence(self):
        weights = TrendingWeights()
        hot = score_confession(
            rating_count=40, rating_avg=4.5, reply_count=20, bookmark_count=10,
            poll_votes=5, age_hours=1, weights=weights, scale_max=5,
        )
        quiet = score_confession(
            rating_count=0, rating_avg=0.0, reply_count=0, bookmark_count=0,
            poll_votes=0, age_hours=1, weights=weights, scale_max=5,
        )
        assert hot > quiet == 0.0

    def test_recency_matters(self):
        weights = TrendingWeights()
        common = dict(
            rating_count=30, rating_avg=4.0, reply_count=10, bookmark_count=5,
            poll_votes=0, weights=weights, scale_max=5,
        )
        fresh = score_confession(age_hours=1, **common)
        stale = score_confession(age_hours=24 * 7, **common)
        assert fresh > stale

    def test_score_is_deterministic(self):
        args = dict(
            rating_count=10, rating_avg=3.0, reply_count=2, bookmark_count=1,
            poll_votes=0, age_hours=3, weights=TrendingWeights(), scale_max=5,
        )
        assert score_confession(
            **args
        ) == score_confession(**args)

    def test_weights_are_tunable(self):
        args = dict(
            rating_count=10, rating_avg=3.0, reply_count=10, bookmark_count=0,
            poll_votes=0, age_hours=2, scale_max=5,
        )
        default = score_confession(weights=TrendingWeights(), **args)
        reply_heavy = score_confession(
            weights=TrendingWeights(replies=10.0), **args
        )
        assert reply_heavy > default


class TestTrendingList:
    async def test_empty_guild_returns_nothing(self, session, settings, guild):
        assert await TrendingService(session).trending(GUILD_ID) == []

    async def test_more_engagement_ranks_higher(self, session, settings, factory):
        popular = await factory.confession(content="popular")
        ignored = await factory.confession(content="ignored")

        ratings = RatingService(session, settings)
        for _ in range(6):
            voter, _ = await factory.member()
            await ratings.rate(
                confession_id=popular.id, guild_id=GUILD_ID,
                voter_internal_user_id=voter.id, value=5,
            )

        entries = await TrendingService(session).trending(GUILD_ID)
        numbers = [entry.public_number for entry in entries]

        assert entries[0].public_number == popular.public_number
        # A confession nobody engaged with scores zero and stays off the board
        # entirely rather than padding it out.
        assert ignored.public_number not in numbers

    async def test_removed_confessions_do_not_trend(self, session, settings, factory):
        from app.services.confession_service import ConfessionService

        confession = await factory.confession(content="removed")
        ratings = RatingService(session, settings)
        for _ in range(3):
            voter, _ = await factory.member()
            await ratings.rate(
                confession_id=confession.id, guild_id=GUILD_ID,
                voter_internal_user_id=voter.id, value=5,
            )
        await ConfessionService(session, settings).remove(
            confession.id, moderator_id=1, reason="test"
        )
        entries = await TrendingService(session).trending(GUILD_ID)
        assert confession.public_number not in [entry.public_number for entry in entries]

    async def test_limit_is_respected(self, session, settings, factory):
        ratings = RatingService(session, settings)
        for index in range(8):
            confession = await factory.confession(content=f"entry {index}")
            voter, _ = await factory.member()
            await ratings.rate(
                confession_id=confession.id, guild_id=GUILD_ID,
                voter_internal_user_id=voter.id, value=4,
            )
        entries = await TrendingService(session).trending(GUILD_ID, limit=5)
        assert len(entries) == 5


class TestHallOfFame:
    async def test_exactly_three_sections(self, session, settings, factory):
        confession = await factory.confession()
        voter, _ = await factory.member()
        await RatingService(session, settings).rate(
            confession_id=confession.id, guild_id=GUILD_ID,
            voter_internal_user_id=voter.id, value=5,
        )
        hall = await TrendingService(session).hall_of_fame(GUILD_ID)
        assert hasattr(hall, "highest_rated")
        assert hasattr(hall, "most_rated")
        assert hasattr(hall, "most_discussed")
        # No extra leaderboards - the product deliberately has only three.
        import dataclasses

        assert [f.name for f in dataclasses.fields(hall)] == [
            "highest_rated",
            "most_rated",
            "most_discussed",
        ]

    async def test_empty_guild_is_handled(self, session, settings, guild):
        hall = await TrendingService(session).hall_of_fame(GUILD_ID)
        assert hall.highest_rated == []
