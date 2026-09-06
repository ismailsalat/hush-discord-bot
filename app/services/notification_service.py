"""Queueing and replaying outbound notices.

Nothing is ever delivered directly from here. Notices are written to the
database first, then a dispatcher attempts DM delivery with retries. If the DM
fails - closed DMs, blocked bot, anything - the row survives and blocking
notices are replayed the next time the user touches Hush.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import NotificationKind
from app.database.models import Notification
from app.database.repositories import GuildRepository, NotificationRepository


class NotificationService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.notifications = NotificationRepository(session)
        self.guilds = GuildRepository(session)

    async def queue_warning(
        self,
        *,
        internal_user_id: str,
        guild_id: int,
        warning_id: str,
        reason: str,
        guild_name: str | None = None,
    ) -> Notification:
        settings = await self.guilds.get_settings(guild_id)
        requires_ack = settings.require_warning_acknowledgement if settings else True
        return await self.notifications.enqueue(
            internal_user_id=internal_user_id,
            guild_id=guild_id,
            kind=NotificationKind.WARNING,
            payload={
                "warning_id": warning_id,
                "reason": reason,
                "guild_name": guild_name,
            },
            is_blocking=True,
            requires_acknowledgement=requires_ack,
        )

    async def queue_ban(
        self,
        *,
        internal_user_id: str,
        guild_id: int,
        ban_id: str,
        reason: str,
        duration_label: str,
        expires_at: str | None,
        guild_name: str | None = None,
    ) -> Notification:
        return await self.notifications.enqueue(
            internal_user_id=internal_user_id,
            guild_id=guild_id,
            kind=NotificationKind.BAN,
            payload={
                "ban_id": ban_id,
                "reason": reason,
                "duration": duration_label,
                "expires_at": expires_at,
                "guild_name": guild_name,
            },
            is_blocking=True,
            requires_acknowledgement=False,
        )


    async def queue_ban_revoked(
        self,
        *,
        internal_user_id: str,
        guild_id: int,
        guild_name: str | None = None,
    ) -> Notification:
        return await self.notifications.enqueue(
            internal_user_id=internal_user_id,
            guild_id=guild_id,
            kind=NotificationKind.BAN_REVOKED,
            payload={"guild_name": guild_name},
            is_blocking=False,
        )

    async def dismiss_warning_notice(
        self, internal_user_id: str, warning_id: str
    ) -> None:
        """Stop a revoked warning from blocking or later DMing the user."""
        for notification in await self.notifications.list_for_user(internal_user_id):
            payload = notification.payload or {}
            if (
                notification.kind == NotificationKind.WARNING
                and payload.get("warning_id") == warning_id
            ):
                await self.notifications.mark_delivered(notification.id)
                await self.notifications.acknowledge(notification.id)

    async def dismiss_ban_notice(
        self, internal_user_id: str, ban_id: str
    ) -> None:
        """Stop a revoked ban notice from replaying as if the ban were active."""
        for notification in await self.notifications.list_for_user(internal_user_id):
            payload = notification.payload or {}
            if (
                notification.kind == NotificationKind.BAN
                and payload.get("ban_id") == ban_id
            ):
                await self.notifications.mark_delivered(notification.id)

    async def queue_confession_removed(
        self, *, internal_user_id: str, guild_id: int, public_number: int, reason: str | None
    ) -> Notification:
        return await self.notifications.enqueue(
            internal_user_id=internal_user_id,
            guild_id=guild_id,
            kind=NotificationKind.CONFESSION_REMOVED,
            payload={"public_number": public_number, "reason": reason},
            is_blocking=False,
        )

    async def queue_follower_update(
        self,
        *,
        follower_internal_user_ids: list[str],
        guild_id: int,
        alias_display: str,
        confession_id: str,
        public_number: int,
        message_link: str | None,
    ) -> int:
        """Fan out a 'they posted again' notice to an alias's followers."""
        payload: dict[str, Any] = {
            "alias_display": alias_display,
            "confession_id": confession_id,
            "public_number": public_number,
            "message_link": message_link,
        }
        for internal_user_id in follower_internal_user_ids:
            await self.notifications.enqueue(
                internal_user_id=internal_user_id,
                guild_id=guild_id,
                kind=NotificationKind.FOLLOW_NEW_CONFESSION,
                payload=payload,
                is_blocking=False,
            )
        return len(follower_internal_user_ids)

    async def outstanding_blocking(
        self, internal_user_id: str, guild_id: int | None = None
    ) -> Notification | None:
        return await self.notifications.get_outstanding_blocking(internal_user_id, guild_id)

    async def mark_shown(self, notification_id: str) -> None:
        await self.notifications.mark_shown(notification_id)

    async def acknowledge(self, notification_id: str) -> Notification | None:
        return await self.notifications.acknowledge(notification_id)

    async def pending_count(self) -> int:
        return await self.notifications.count_pending()
