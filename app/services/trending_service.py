"""Trending and Hall of Fame.

The scoring algorithm lives in one place, as a pure function over plain numbers,
so it can be tuned or replaced without touching SQL or the Discord layer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories import (
    AliasRepository,
    ConfessionRepository,
    GuildRepository,
    RatingRepository,
)
from app.security.identifiers import format_alias
from app.services.dto import HallOfFame, HallOfFameEntry, TrendingEntry
from app.utils.text import one_line
from app.utils.time import ensure_utc, utcnow


@dataclass(frozen=True, slots=True)
class TrendingWeights:
    """Tunable inputs to the trending score.

    ``gravity`` controls how quickly older posts fall away: higher means a
    faster decay and a more volatile board.
    """

    rating_count: float = 1.0
    rating_quality: float = 0.8
    replies: float = 1.5
    bookmarks: float = 1.2
    poll_votes: float = 0.6
    gravity: float = 1.5
    half_life_hours: float = 12.0


DEFAULT_WEIGHTS = TrendingWeights()


def score_confession(
    *,
    rating_count: int,
    rating_avg: float,
    reply_count: int,
    bookmark_count: int,
    poll_votes: int,
    age_hours: float,
    scale_max: int = 5,
    weights: TrendingWeights = DEFAULT_WEIGHTS,
) -> float:
    """Time-decayed engagement score.

    Engagement is compressed with ``log1p`` so a handful of very popular posts
    cannot permanently occupy the board, then divided by an age term so recent
    activity surfaces. Quality is a normalised multiplier on volume, meaning a
    highly-rated post beats a widely-but-poorly-rated one.
    """
    quality = (rating_avg / scale_max) if (rating_avg and scale_max) else 0.0

    engagement = (
        weights.rating_count * math.log1p(rating_count)
        + weights.rating_quality * quality * math.log1p(rating_count)
        + weights.replies * math.log1p(reply_count)
        + weights.bookmarks * math.log1p(bookmark_count)
        + weights.poll_votes * math.log1p(poll_votes)
    )
    if engagement <= 0:
        return 0.0

    decay = math.pow((age_hours / weights.half_life_hours) + 2.0, weights.gravity)
    return engagement / decay


class TrendingService:
    def __init__(self, session: AsyncSession, *, weights: TrendingWeights = DEFAULT_WEIGHTS):
        # ``weights`` is keyword-only on purpose: it is the only other argument
        # and a positional second argument here would silently bind the wrong
        # object rather than failing loudly.
        self.session = session
        self.weights = weights
        self.confessions = ConfessionRepository(session)
        self.ratings = RatingRepository(session)
        self.aliases = AliasRepository(session)
        self.guilds = GuildRepository(session)

    async def trending(
        self, guild_id: int, *, limit: int = 5, window_hours: int = 24
    ) -> list[TrendingEntry]:
        settings = await self.guilds.get_settings(guild_id)
        scale_max = settings.rating_scale_max if settings else 5

        since = utcnow() - timedelta(hours=window_hours)
        rows = await self.confessions.engagement_rows(guild_id, since=since, limit=200)
        now = utcnow()

        scored: list[tuple[float, dict]] = []
        for row in rows:
            confession = row["confession"]
            created = ensure_utc(confession.created_at) or now
            age_hours = max(0.0, (now - created).total_seconds() / 3600)
            score = score_confession(
                rating_count=row["rating_count"],
                rating_avg=row["rating_avg"],
                reply_count=row["reply_count"],
                bookmark_count=row["bookmark_count"],
                poll_votes=row["poll_votes"],
                age_hours=age_hours,
                scale_max=scale_max,
                weights=self.weights,
            )
            if score > 0:
                scored.append((score, row))

        scored.sort(key=lambda item: item[0], reverse=True)

        entries: list[TrendingEntry] = []
        for score, row in scored[:limit]:
            confession = row["confession"]
            alias = await self.aliases.get(confession.alias_id)
            entries.append(
                TrendingEntry(
                    confession_id=confession.id,
                    public_number=confession.public_number,
                    alias_display=format_alias(alias.public_alias) if alias else "Anon",
                    score=round(score, 4),
                    average_rating=row["rating_avg"] or None,
                    rating_count=row["rating_count"],
                    reply_count=row["reply_count"],
                    preview=one_line(confession.content, 50),
                )
            )
        return entries

    async def hall_of_fame(self, guild_id: int, *, limit: int = 3) -> HallOfFame:
        """Three sections only. Deliberately not twenty leaderboards."""
        highest = await self.ratings.highest_rated(guild_id, minimum_ratings=3, limit=limit)
        most_rated = await self.ratings.most_rated(guild_id, limit=limit)
        most_discussed = await self.ratings.most_discussed(guild_id, limit=limit)

        settings = await self.guilds.get_settings(guild_id)
        scale_max = settings.rating_scale_max if settings else 5

        async def entry(confession, metric: str) -> HallOfFameEntry:
            alias = await self.aliases.get(confession.alias_id)
            return HallOfFameEntry(
                confession_id=confession.id,
                public_number=confession.public_number,
                alias_display=format_alias(alias.public_alias) if alias else "Anon",
                primary_metric=metric,
                preview=one_line(confession.content, 44),
            )

        return HallOfFame(
            highest_rated=[
                await entry(c, f"{avg:.1f} / {scale_max} ({count} ratings)")
                for c, avg, count in highest
            ],
            most_rated=[await entry(c, f"{count} ratings") for c, count in most_rated],
            most_discussed=[
                await entry(c, f"{c.reply_count} replies") for c in most_discussed
            ],
        )
