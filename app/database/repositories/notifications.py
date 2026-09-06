"""Outbound notification queue access."""

from __future__ import annotations

from datetime import timedelta

from typing import Any

from sqlalchemy import or_, select

from app.core.constants import NotificationKind, NotificationStatus
from app.database.models import Notification
from app.database.repositories.base import BaseRepository
from app.utils.time import ensure_utc, utcnow


class NotificationRepository(BaseRepository):
    async def get(self, notification_id: str) -> Notification | None:
        return await self.session.get(Notification, notification_id)

    async def enqueue(
        self,
        *,
        internal_user_id: str,
        kind: NotificationKind,
        payload: dict[str, Any],
        guild_id: int | None = None,
        is_blocking: bool = False,
        requires_acknowledgement: bool = False,
    ) -> Notification:
        notification = Notification(
            internal_user_id=internal_user_id,
            guild_id=guild_id,
            kind=kind,
            payload=payload,
            is_blocking=is_blocking,
            requires_acknowledgement=requires_acknowledgement,
        )
        self.session.add(notification)
        await self.session.flush()
        return notification

    async def list_pending(self, *, max_attempts: int = 3, limit: int = 50) -> list[Notification]:
        result = await self.session.execute(
            select(Notification)
            .where(
                Notification.status == NotificationStatus.PENDING,
                Notification.attempts < max_attempts,
            )
            .order_by(Notification.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_outstanding_blocking(
        self, internal_user_id: str, guild_id: int | None = None
    ) -> Notification | None:
        """The moderation notice that must be shown before anything else.

        This is what stops a closed DM from swallowing a punishment: delivery
        may have failed, but the row is still here and still blocking.
        """
        query = select(Notification).where(
            Notification.internal_user_id == internal_user_id,
            Notification.is_blocking.is_(True),
            or_(
                Notification.shown_at.is_(None),
                (Notification.requires_acknowledgement.is_(True))
                & (Notification.acknowledged_at.is_(None)),
            ),
        )
        if guild_id is not None:
            query = query.where(
                or_(Notification.guild_id == guild_id, Notification.guild_id.is_(None))
            )
        result = await self.session.execute(query.order_by(Notification.created_at.asc()).limit(1))
        return result.scalar_one_or_none()

    async def mark_attempt(self, notification_id: str) -> None:
        notification = await self.get(notification_id)
        if notification is not None:
            notification.attempts += 1
            notification.last_attempt_at = utcnow()
            await self.session.flush()

    async def mark_delivered(self, notification_id: str) -> None:
        notification = await self.get(notification_id)
        if notification is not None:
            notification.status = NotificationStatus.DELIVERED
            notification.delivered_at = utcnow()
            if notification.shown_at is None:
                notification.shown_at = utcnow()
            await self.session.flush()

    async def mark_failed(
        self, notification_id: str, reason: str, *, max_attempts: int = 3
    ) -> None:
        """Record a delivery failure without discarding blocking notice history."""
        notification = await self.get(notification_id)
        if notification is not None:
            notification.delivery_failed_at = utcnow()
            notification.failure_reason = reason[:300]
            if notification.attempts >= max_attempts:
                notification.status = NotificationStatus.FAILED
            await self.session.flush()

    async def mark_shown(self, notification_id: str) -> None:
        """Called when the notice is displayed in-app instead of via DM."""
        notification = await self.get(notification_id)
        if notification is not None and notification.shown_at is None:
            notification.shown_at = utcnow()
            await self.session.flush()

    async def acknowledge(self, notification_id: str) -> Notification | None:
        notification = await self.get(notification_id)
        if notification is not None:
            notification.acknowledged_at = utcnow()
            if notification.shown_at is None:
                notification.shown_at = utcnow()
            await self.session.flush()
        return notification

    async def count_pending(self) -> int:
        from sqlalchemy import func

        result = await self.session.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.status == NotificationStatus.PENDING)
        )
        return int(result.scalar_one())

    async def list_for_user(self, internal_user_id: str) -> list[Notification]:
        result = await self.session.execute(
            select(Notification)
            .where(Notification.internal_user_id == internal_user_id)
            .order_by(Notification.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_deliverable(
        self,
        *,
        limit: int = 25,
        max_attempts: int = 3,
        backoff_minutes: tuple[int, ...] = (0, 15, 60),
    ) -> list[Notification]:
        """Pending notifications whose backoff window has elapsed.

        The backoff widens with each failed attempt so a user with closed DMs
        is not retried every minute forever.
        """
        candidates = await self.list_pending(max_attempts=max_attempts, limit=limit * 3)
        now = utcnow()
        ready: list[Notification] = []

        for notification in candidates:
            attempts = notification.attempts or 0
            if attempts == 0:
                ready.append(notification)
            else:
                index = min(attempts, len(backoff_minutes) - 1)
                last = ensure_utc(notification.delivery_failed_at) or ensure_utc(
                    notification.created_at
                )
                if last is None or now >= last + timedelta(minutes=backoff_minutes[index]):
                    ready.append(notification)
            if len(ready) >= limit:
                break
        return ready
