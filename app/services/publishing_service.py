"""Orchestrates getting a confession from draft to a live Discord message.

The hard requirement is that these two never disagree:

* the database believes a confession exists, but no message was ever posted
* a message exists, but the database has no record of it

The flow is therefore: write PENDING and commit -> post to Discord -> mark
POSTED and commit. A crash between stages leaves a PENDING row, which the
reconciliation task finds and repairs. Nothing is ever lost silently, and the
author's text is preserved as a draft on any failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.config.settings import Settings
from app.core.exceptions import HushError
from app.database.session import Database
from app.logging.error_ids import ErrorReport, report_exception
from app.logging.setup import app_logger
from app.security.identifiers import new_idempotency_key
from app.services.confession_service import ConfessionService
from app.services.dto import ConfessionView


@dataclass(frozen=True, slots=True)
class PublishTarget:
    guild_id: int
    channel_id: int


@dataclass(frozen=True, slots=True)
class PublishedMessage:
    message_id: int
    channel_id: int


class ConfessionPublisher(Protocol):
    """Implemented by the Discord layer; keeps the API out of this service."""

    async def publish(self, view: ConfessionView, target: PublishTarget) -> PublishedMessage: ...

    async def refresh(self, view: ConfessionView, message_id: int, channel_id: int) -> None: ...

    async def withdraw(self, message_id: int, channel_id: int) -> None: ...


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    ok: bool
    confession_id: str | None = None
    public_number: int | None = None
    view: ConfessionView | None = None
    message_link: str | None = None
    error: HushError | None = None
    error_report: ErrorReport | None = None
    draft_saved: bool = False


class PublishingService:
    def __init__(self, database: Database, settings: Settings, publisher: ConfessionPublisher):
        self.database = database
        self.settings = settings
        self.publisher = publisher

    async def submit(
        self,
        *,
        internal_user_id: str,
        guild_id: int,
        content: str,
        alias_id: str | None = None,
        parent_confession_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> SubmissionResult:
        """Full submission flow with draft preservation on every failure path.

        ``alias_id`` is optional: callers should not have to resolve the
        author's current anonymous identity themselves, and doing it here means
        a rotation that happens mid-compose still posts under the right alias.
        """
        idempotency_key = idempotency_key or new_idempotency_key()

        # Stage 1: validate + persist as PENDING, then commit.
        try:
            async with self.database.session() as session:
                service = ConfessionService(session, self.settings)
                resolved_alias = alias_id
                if resolved_alias is None:
                    from app.services.alias_service import AliasService

                    alias = await AliasService(
                        session,
                        default_rotation_days=self.settings.default_alias_rotation_days,
                    ).get_or_create_current(internal_user_id, guild_id)
                    resolved_alias = alias.id

                confession = await service.prepare(
                    internal_user_id=internal_user_id,
                    guild_id=guild_id,
                    alias_id=resolved_alias,
                    content=content,
                    parent_confession_id=parent_confession_id,
                    idempotency_key=idempotency_key,
                )
                confession_id = confession.id
                public_number = confession.public_number
        except HushError as exc:
            # Validation problems are the user's to fix - keep their text.
            await self._save_draft(internal_user_id, guild_id, content, parent_confession_id, str(exc))
            return SubmissionResult(ok=False, error=exc, draft_saved=True)
        except Exception as exc:
            report = report_exception(
                exc, operation="confession.prepare", guild_id=guild_id,
                user_reference=internal_user_id,
            )
            await self._save_draft(
                internal_user_id, guild_id, content, parent_confession_id, report.error_id
            )
            return SubmissionResult(ok=False, error_report=report, draft_saved=True)

        # Stage 2: post to Discord.
        try:
            async with self.database.session() as session:
                service = ConfessionService(session, self.settings)
                view = await service.build_view(await service.get(confession_id))
                channel_id = (await service.guilds.get_settings(guild_id)).confession_channel_id

            posted = await self.publisher.publish(
                view, PublishTarget(guild_id=guild_id, channel_id=int(channel_id))
            )
        except Exception as exc:
            async with self.database.session() as session:
                await ConfessionService(session, self.settings).mark_failed(confession_id)
            report = report_exception(
                exc, operation="confession.publish", guild_id=guild_id,
                user_reference=internal_user_id, confession_id=confession_id,
            )
            await self._save_draft(
                internal_user_id, guild_id, content, parent_confession_id, report.error_id
            )
            error = exc if isinstance(exc, HushError) else None
            return SubmissionResult(
                ok=False, confession_id=confession_id, error=error,
                error_report=None if error else report, draft_saved=True,
            )

        # Stage 3: record the message ids and clear the draft.
        async with self.database.session() as session:
            service = ConfessionService(session, self.settings)
            await service.finalize_posted(
                confession_id, message_id=posted.message_id, channel_id=posted.channel_id
            )
            confession = await service.get(confession_id)
            view = await service.build_view(confession)
            from app.database.repositories import DraftRepository

            await DraftRepository(session).delete_for_user(internal_user_id, guild_id)

        # Follower notifications are deliberately best-effort and run in their
        # own transaction.  A notification failure must never roll back a
        # confession that Discord already accepted.
        try:
            async with self.database.session() as session:
                from app.services.follow_service import FollowService
                from app.services.notification_service import NotificationService

                followers = await FollowService(session).followers_to_notify(
                    confession.alias_id
                )
                if followers:
                    await NotificationService(session).queue_follower_update(
                        follower_internal_user_ids=followers,
                        guild_id=guild_id,
                        alias_display=view.alias_display,
                        confession_id=confession_id,
                        public_number=public_number,
                        message_link=view.message_link,
                    )
        except Exception as exc:
            report_exception(
                exc,
                operation="confession.follower_notifications",
                guild_id=guild_id,
                confession_id=confession_id,
            )

        app_logger().info(
            "confession_posted",
            guild_id=guild_id,
            confession_id=confession_id,
            public_number=public_number,
            is_update=parent_confession_id is not None,
        )
        return SubmissionResult(
            ok=True,
            confession_id=confession_id,
            public_number=public_number,
            view=view,
            message_link=view.message_link,
        )

    async def refresh_message(self, confession_id: str) -> bool:
        """Re-render a posted confession (after a rating, update or poll)."""
        try:
            async with self.database.session() as session:
                service = ConfessionService(session, self.settings)
                confession = await service.get(confession_id)
                if not confession.discord_message_id or confession.is_deleted:
                    return False
                view = await service.build_view(confession)
                message_id = confession.discord_message_id
                channel_id = confession.discord_channel_id
            await self.publisher.refresh(view, int(message_id), int(channel_id))
            return True
        except Exception as exc:
            report_exception(exc, operation="confession.refresh", confession_id=confession_id)
            return False

    async def withdraw_message(self, confession_id: str) -> bool:
        """Delete the public message for a removed confession.

        The database row is kept (soft delete) so moderation history survives;
        only the visible message goes away.
        """
        try:
            async with self.database.session() as session:
                confession = await ConfessionService(session, self.settings).get(confession_id)
                message_id = confession.discord_message_id
                channel_id = confession.discord_channel_id
            if not message_id or not channel_id:
                return False
            await self.publisher.withdraw(int(message_id), int(channel_id))
            return True
        except Exception as exc:
            report_exception(exc, operation="confession.withdraw", confession_id=confession_id)
            return False

    async def _save_draft(
        self,
        internal_user_id: str,
        guild_id: int,
        content: str,
        parent_confession_id: str | None,
        last_error: str | None,
    ) -> None:
        """Preserve the author's text. Never let a failure discard it."""
        from app.database.repositories import DraftRepository

        try:
            async with self.database.session() as session:
                await DraftRepository(session).save(
                    internal_user_id=internal_user_id,
                    guild_id=guild_id,
                    content=content,
                    expiry_minutes=self.settings.draft_expiry_minutes,
                    parent_confession_id=parent_confession_id,
                    last_error=last_error,
                )
        except Exception as exc:  # pragma: no cover - last-resort safety net
            report_exception(exc, operation="draft.save", guild_id=guild_id)
