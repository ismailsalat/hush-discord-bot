"""Notification delivery.

Notices are queued by the moderation service and delivered here, never inline,
so a closed DM cannot block or fail a moderator's action. Delivery is retried
with a widening backoff; once attempts run out the notice stays outstanding and
is shown inside the app the next time the user interacts.
"""

from __future__ import annotations

import discord

from app.core.constants import NotificationKind
from app.database.repositories import NotificationRepository, UserRepository
from app.logging.setup import app_logger
from app.utils.time import ensure_utc

#: Minutes to wait before each retry.
BACKOFF_MINUTES = (0, 15, 60)


class NotificationDispatcher:
    def __init__(self, client: discord.Client, runtime) -> None:
        self.client = client
        self.runtime = runtime

    def _embed(self, notification) -> discord.Embed | None:
        payload = notification.payload or {}
        embeds = self.runtime.moderation_embeds

        if notification.kind == NotificationKind.WARNING:
            return embeds.warning_notice(
                reason=payload.get("reason", "Not specified"),
                guild_name=payload.get("guild_name"),
            )
        if notification.kind == NotificationKind.BAN:
            expires_at = None
            if payload.get("expires_at"):
                from datetime import datetime

                try:
                    expires_at = ensure_utc(datetime.fromisoformat(payload["expires_at"]))
                except ValueError:
                    expires_at = None
            return embeds.ban_notice(
                duration=payload.get("duration", "Unknown"),
                reason=payload.get("reason", "Not specified"),
                guild_name=payload.get("guild_name"),
                expires_at=expires_at,
            )
        if notification.kind == NotificationKind.BAN_REVOKED:
            return embeds.ban_revoked(payload.get("guild_name"))
        if notification.kind == NotificationKind.CONFESSION_REMOVED:
            return embeds.confession_removed_notice(
                public_number=payload.get("public_number", 0),
                reason=payload.get("reason"),
            )
        if notification.kind == NotificationKind.FOLLOW_NEW_CONFESSION:
            return embeds.follower_update(
                alias_display=payload.get("alias_display", "Someone you follow"),
                public_number=payload.get("public_number", 0),
                message_link=payload.get("message_link"),
            )
        return None

    async def deliver_pending(self, limit: int = 25) -> str | None:
        """Attempt delivery of queued notifications."""
        delivered = failed = 0

        async with self.runtime.session() as session:
            notifications = NotificationRepository(session)
            users = UserRepository(session)
            pending = await notifications.list_deliverable(
                limit=limit,
                max_attempts=self.runtime.settings.notification_max_attempts,
                backoff_minutes=BACKOFF_MINUTES,
            )

            for notification in pending:
                embed = self._embed(notification)
                if embed is None:
                    await notifications.mark_delivered(notification.id)
                    continue

                user_row = await users.get_by_internal_id(notification.internal_user_id)
                if user_row is None:
                    await notifications.mark_attempt(notification.id)
                    await notifications.mark_failed(
                        notification.id,
                        "unknown user",
                        max_attempts=self.runtime.settings.notification_max_attempts,
                    )
                    failed += 1
                    continue

                view = None
                if (
                    notification.requires_acknowledgement
                    and notification.acknowledged_at is None
                ):
                    from app.views.notices import NoticeAcknowledgeView

                    view = NoticeAcknowledgeView(notification.id)

                # Count the attempt before touching Discord so retry/backoff
                # cannot get stuck at zero when DMs are closed.
                await notifications.mark_attempt(notification.id)

                try:
                    user = self.client.get_user(int(user_row.discord_user_id))
                    if user is None:
                        user = await self.client.fetch_user(int(user_row.discord_user_id))
                    await user.send(embed=embed, view=view)
                    await notifications.mark_delivered(notification.id)
                    delivered += 1
                except (discord.Forbidden, discord.HTTPException) as exc:
                    # DMs closed or Discord refused. Blocking notices remain
                    # replayable in-app even after outbound retries are spent.
                    await notifications.mark_failed(
                        notification.id,
                        type(exc).__name__,
                        max_attempts=self.runtime.settings.notification_max_attempts,
                    )
                    failed += 1

        if delivered or failed:
            app_logger().info("notifications_dispatched", delivered=delivered, failed=failed)
            return f"delivered {delivered}, failed {failed}"
        return None
