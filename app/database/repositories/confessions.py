"""Confession persistence, including numbering, update chains and trending."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import Select, and_, func, select, update
from sqlalchemy.exc import IntegrityError

from app.core.constants import ConfessionStatus
from app.database.models import Bookmark, Confession, Poll, PollVote, Rating
from app.database.repositories.base import BaseRepository
from app.utils.time import utcnow

#: Retries when two confessions race for the same public number.
_NUMBER_ALLOCATION_RETRIES = 5


class ConfessionRepository(BaseRepository):
    # --- Reads -------------------------------------------------------------

    async def get_by_id(self, confession_id: str) -> Confession | None:
        return await self.session.get(Confession, confession_id)

    async def get_by_public_number(self, guild_id: int, number: int) -> Confession | None:
        result = await self.session.execute(
            select(Confession).where(
                Confession.guild_id == guild_id, Confession.public_number == number
            )
        )
        return result.scalar_one_or_none()

    async def get_by_message_id(self, message_id: int) -> Confession | None:
        result = await self.session.execute(
            select(Confession).where(Confession.discord_message_id == message_id)
        )
        return result.scalar_one_or_none()

    def _visible(self) -> Select:
        return select(Confession).where(
            Confession.is_deleted.is_(False), Confession.status == ConfessionStatus.POSTED
        )

    async def list_for_alias(self, alias_id: str, *, limit: int = 25) -> list[Confession]:
        """Public confessions posted under one alias, newest first."""
        result = await self.session.execute(
            self._visible()
            .where(Confession.alias_id == alias_id)
            .order_by(Confession.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_for_alias(self, alias_id: str) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(Confession)
            .where(
                Confession.alias_id == alias_id,
                Confession.is_deleted.is_(False),
                Confession.status == ConfessionStatus.POSTED,
            )
        )
        return int(result.scalar_one())

    async def list_for_user(
        self, internal_user_id: str, guild_id: int | None = None, *, include_deleted: bool = True
    ) -> list[Confession]:
        """Every confession by an internal user. Moderation/export use only."""
        query = select(Confession).where(Confession.internal_user_id == internal_user_id)
        if guild_id is not None:
            query = query.where(Confession.guild_id == guild_id)
        if not include_deleted:
            query = query.where(Confession.is_deleted.is_(False))
        result = await self.session.execute(query.order_by(Confession.created_at.desc()))
        return list(result.scalars().all())

    async def list_for_guild(
        self, guild_id: int, *, include_deleted: bool = True, limit: int | None = None
    ) -> list[Confession]:
        query = select(Confession).where(Confession.guild_id == guild_id)
        if not include_deleted:
            query = query.where(Confession.is_deleted.is_(False))
        query = query.order_by(Confession.created_at.desc())
        if limit:
            query = query.limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def list_chain(self, root_confession_id: str) -> list[Confession]:
        """Whole update chain in posting order."""
        result = await self.session.execute(
            select(Confession)
            .where(
                (Confession.root_confession_id == root_confession_id)
                | (Confession.id == root_confession_id)
            )
            .order_by(Confession.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_child_updates(self, confession_id: str) -> list[Confession]:
        result = await self.session.execute(
            self._visible()
            .where(Confession.parent_confession_id == confession_id)
            .order_by(Confession.created_at.asc())
        )
        return list(result.scalars().all())

    async def find_pending(self, older_than_minutes: int = 5) -> list[Confession]:
        """Rows stuck in PENDING - reconciliation input."""
        cutoff = utcnow() - timedelta(minutes=older_than_minutes)
        result = await self.session.execute(
            select(Confession).where(
                Confession.status == ConfessionStatus.PENDING, Confession.created_at < cutoff
            )
        )
        return list(result.scalars().all())

    async def recent_fingerprint_exists(
        self, internal_user_id: str, guild_id: int, fingerprint: str, *, minutes: int = 60
    ) -> bool:
        """Detect a user reposting identical text (spam control)."""
        cutoff = utcnow() - timedelta(minutes=minutes)
        result = await self.session.execute(
            select(Confession.id).where(
                Confession.internal_user_id == internal_user_id,
                Confession.guild_id == guild_id,
                Confession.content_fingerprint == fingerprint,
                Confession.created_at >= cutoff,
                Confession.is_deleted.is_(False),
                Confession.status.in_((ConfessionStatus.PENDING, ConfessionStatus.POSTED)),
            )
        )
        return result.first() is not None

    async def get_by_idempotency_key(self, key: str) -> Confession | None:
        result = await self.session.execute(
            select(Confession).where(Confession.idempotency_key == key)
        )
        return result.scalar_one_or_none()

    # --- Writes ------------------------------------------------------------

    async def _next_public_number(self, guild_id: int) -> int:
        result = await self.session.execute(
            select(func.coalesce(func.max(Confession.public_number), 0)).where(
                Confession.guild_id == guild_id
            )
        )
        return int(result.scalar_one()) + 1

    async def create_pending(
        self,
        *,
        guild_id: int,
        internal_user_id: str,
        alias_id: str,
        content: str,
        content_fingerprint: str,
        parent_confession_id: str | None = None,
        root_confession_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> Confession:
        """Insert the row *before* posting to Discord.

        Written as PENDING so a crash between database and Discord leaves a
        recoverable row rather than a lost confession. The unique constraint on
        ``(guild_id, public_number)`` is the real guard against numbering races;
        we simply retry on collision.
        """
        last_error: Exception | None = None
        for _ in range(_NUMBER_ALLOCATION_RETRIES):
            confession = Confession(
                guild_id=guild_id,
                public_number=await self._next_public_number(guild_id),
                internal_user_id=internal_user_id,
                alias_id=alias_id,
                content=content,
                content_fingerprint=content_fingerprint,
                parent_confession_id=parent_confession_id,
                root_confession_id=root_confession_id,
                idempotency_key=idempotency_key,
                status=ConfessionStatus.PENDING,
            )
            try:
                # A savepoint handles the expected public-number race without
                # rolling back unrelated work in the outer transaction.
                async with self.session.begin_nested():
                    self.session.add(confession)
                    await self.session.flush()
            except IntegrityError as exc:
                last_error = exc
                if idempotency_key:
                    existing = await self.get_by_idempotency_key(idempotency_key)
                    if existing is not None:
                        return existing
                continue

            if confession.root_confession_id is None:
                confession.root_confession_id = confession.id
                await self.session.flush()
            return confession
        raise last_error or RuntimeError("could not allocate a confession number")

    async def mark_posted(self, confession_id: str, *, message_id: int, channel_id: int) -> None:
        await self.session.execute(
            update(Confession)
            .where(Confession.id == confession_id)
            .values(
                status=ConfessionStatus.POSTED,
                discord_message_id=message_id,
                discord_channel_id=channel_id,
                updated_at=utcnow(),
            )
        )

    async def mark_failed(self, confession_id: str) -> None:
        await self.session.execute(
            update(Confession)
            .where(Confession.id == confession_id)
            .values(status=ConfessionStatus.FAILED, updated_at=utcnow())
        )

    async def mark_deleted(
        self, confession_id: str, *, moderator_id: int | None, reason: str | None
    ) -> None:
        """Soft delete: the row survives for audit, the message does not."""
        await self.session.execute(
            update(Confession)
            .where(Confession.id == confession_id)
            .values(
                is_deleted=True,
                deleted_at=utcnow(),
                deleted_by=moderator_id,
                delete_reason=reason,
                status=ConfessionStatus.REMOVED,
                updated_at=utcnow(),
            )
        )

    async def increment_reply_count(self, confession_id: str, delta: int = 1) -> None:
        await self.session.execute(
            update(Confession)
            .where(Confession.id == confession_id)
            .values(reply_count=Confession.reply_count + delta)
        )

    async def purge(self, confession_id: str) -> None:
        """Hard delete. Only reachable through an explicit retention purge."""
        confession = await self.get_by_id(confession_id)
        if confession is not None:
            await self.session.delete(confession)

    # --- Aggregates --------------------------------------------------------

    async def rating_summary(self, confession_id: str) -> tuple[float | None, int]:
        """``(average, count)`` computed from the ratings table, never cached."""
        result = await self.session.execute(
            select(func.avg(Rating.value), func.count(Rating.id)).where(
                Rating.confession_id == confession_id
            )
        )
        average, count = result.one()
        return (float(average) if average is not None else None, int(count or 0))

    async def bookmark_count(self, confession_id: str) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Bookmark).where(Bookmark.confession_id == confession_id)
        )
        return int(result.scalar_one())

    async def alias_rating_summary(self, alias_id: str) -> tuple[float | None, int]:
        """Average rating across every visible confession under one alias."""
        result = await self.session.execute(
            select(func.avg(Rating.value), func.count(Rating.id))
            .select_from(Rating)
            .join(Confession, Confession.id == Rating.confession_id)
            .where(
                Confession.alias_id == alias_id,
                Confession.is_deleted.is_(False),
                Confession.status == ConfessionStatus.POSTED,
            )
        )
        average, count = result.one()
        return (float(average) if average is not None else None, int(count or 0))

    async def most_rated_for_alias(self, alias_id: str) -> tuple[Confession, int] | None:
        result = await self.session.execute(
            select(Confession, func.count(Rating.id).label("rating_count"))
            .join(Rating, Rating.confession_id == Confession.id)
            .where(
                Confession.alias_id == alias_id,
                Confession.is_deleted.is_(False),
                Confession.status == ConfessionStatus.POSTED,
            )
            .group_by(Confession.id)
            .order_by(func.count(Rating.id).desc())
            .limit(1)
        )
        row = result.first()
        return (row[0], int(row[1])) if row else None

    async def engagement_rows(
        self, guild_id: int, *, since: datetime | None = None, limit: int = 200
    ) -> list[dict]:
        """Raw engagement metrics feeding :class:`TrendingService`.

        Returns plain dicts so the scoring algorithm stays free of SQL and can
        be tuned or replaced without touching this layer.
        """
        # Correlated scalar subqueries rather than parallel outer joins: joining
        # three one-to-many tables at once would multiply rows together and
        # skew every aggregate.
        rating_count = (
            select(func.count(Rating.id))
            .where(Rating.confession_id == Confession.id)
            .scalar_subquery()
            .label("rating_count")
        )
        rating_avg = (
            select(func.avg(Rating.value))
            .where(Rating.confession_id == Confession.id)
            .scalar_subquery()
            .label("rating_avg")
        )
        bookmark_count = (
            select(func.count(Bookmark.id))
            .where(Bookmark.confession_id == Confession.id)
            .scalar_subquery()
            .label("bookmark_count")
        )
        poll_votes = (
            select(func.count(PollVote.id))
            .join(Poll, Poll.id == PollVote.poll_id)
            .where(Poll.confession_id == Confession.id)
            .scalar_subquery()
            .label("poll_votes")
        )

        query = (
            select(Confession, rating_count, rating_avg, bookmark_count, poll_votes)
            .where(
                and_(
                    Confession.guild_id == guild_id,
                    Confession.is_deleted.is_(False),
                    Confession.status == ConfessionStatus.POSTED,
                )
            )
            .order_by(Confession.created_at.desc())
            .limit(limit)
        )
        if since is not None:
            query = query.where(Confession.created_at >= since)

        result = await self.session.execute(query)
        rows: list[dict] = []
        for confession, ratings, average, bookmarks, votes in result.all():
            rows.append(
                {
                    "confession": confession,
                    "rating_count": int(ratings or 0),
                    "rating_avg": float(average) if average is not None else 0.0,
                    "bookmark_count": int(bookmarks or 0),
                    "poll_votes": int(votes or 0),
                    "reply_count": confession.reply_count,
                }
            )
        return rows
