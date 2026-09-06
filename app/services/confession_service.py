"""Confession creation, rendering data and removal.

This service is deliberately Discord-free. It owns *what* a confession is;
:mod:`app.services.publishing_service` owns the multi-stage dance of getting it
onto Discord without the database and Discord ever disagreeing.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.core.constants import ConfessionStatus, LedgerAction
from app.core.exceptions import (
    ConfessionNotFoundError,
    DuplicateSubmissionError,
    GuildNotConfiguredError,
    NotConfessionAuthorError,
    UpdatesDisabledError,
)
from app.database.models import Confession
from app.database.repositories import (
    AliasRepository,
    ConfessionRepository,
    GuildRepository,
    ModerationRepository,
    PollRepository,
)
from app.security.identifiers import format_alias
from app.services.dto import ConfessionStats, ConfessionView
from app.utils.text import content_fingerprint, one_line
from app.utils.validators import validate_confession


class ConfessionService:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.session = session
        self.settings = settings
        self.confessions = ConfessionRepository(session)
        self.aliases = AliasRepository(session)
        self.guilds = GuildRepository(session)
        self.polls = PollRepository(session)
        self.ledger = ModerationRepository(session)

    # --- Creation ----------------------------------------------------------

    async def prepare(
        self,
        *,
        internal_user_id: str,
        guild_id: int,
        alias_id: str,
        content: str,
        parent_confession_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> Confession:
        """Validate and insert a PENDING confession.

        Nothing is shown to the server yet. The row exists first so that a
        failure during posting is recoverable rather than silent data loss.
        """
        settings = await self.guilds.get_settings(guild_id)
        if settings is None or not settings.is_configured:
            raise GuildNotConfiguredError()

        # Idempotency is about *retries*, so a repeated key returns the row
        # that was already created rather than erroring. This is what makes a
        # double click or a network retry safe.
        if idempotency_key:
            existing = await self.confessions.get_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing

        text = validate_confession(content, settings.confession_character_limit)
        fingerprint = content_fingerprint(text)

        # The same person posting identical text again within the hour is a
        # duplicate, not a rate limit - say so plainly.
        if await self.confessions.recent_fingerprint_exists(
            internal_user_id, guild_id, fingerprint
        ):
            raise DuplicateSubmissionError()

        parent: Confession | None = None
        root_id: str | None = None
        if parent_confession_id:
            if not settings.updates_enabled:
                raise UpdatesDisabledError()
            parent = await self.confessions.get_by_id(parent_confession_id)
            if parent is None or parent.is_deleted:
                raise ConfessionNotFoundError()
            if parent.internal_user_id != internal_user_id:
                raise NotConfessionAuthorError(
                    "only the author may post an update",
                    user_message="Only the person who posted a confession can post an update to it.",
                )
            root_id = parent.root_confession_id or parent.id

        return await self.confessions.create_pending(
            guild_id=guild_id,
            internal_user_id=internal_user_id,
            alias_id=alias_id,
            content=text,
            content_fingerprint=fingerprint,
            parent_confession_id=parent.id if parent else None,
            root_confession_id=root_id,
            idempotency_key=idempotency_key,
        )

    async def finalize_posted(self, confession_id: str, *, message_id: int, channel_id: int) -> None:
        """Mark a confession live and record it in the ledger."""
        await self.confessions.mark_posted(
            confession_id, message_id=message_id, channel_id=channel_id
        )
        confession = await self.confessions.get_by_id(confession_id)
        if confession is not None:
            await self.ledger.record(
                LedgerAction.CONFESSION_CREATED,
                internal_user_id=confession.internal_user_id,
                guild_id=confession.guild_id,
                confession_id=confession.id,
                alias_id=confession.alias_id,
                meta={
                    "public_number": confession.public_number,
                    "is_update": confession.is_update,
                },
            )

    async def mark_failed(self, confession_id: str) -> None:
        await self.confessions.mark_failed(confession_id)

    # --- Reads -------------------------------------------------------------

    async def get(self, confession_id: str) -> Confession:
        confession = await self.confessions.get_by_id(confession_id)
        if confession is None:
            raise ConfessionNotFoundError()
        return confession

    async def get_visible(self, confession_id: str) -> Confession:
        confession = await self.get(confession_id)
        if confession.is_deleted or confession.status == ConfessionStatus.REMOVED:
            raise ConfessionNotFoundError()
        return confession

    async def get_by_number(self, guild_id: int, number: int) -> Confession:
        confession = await self.confessions.get_by_public_number(guild_id, number)
        if confession is None or confession.is_deleted:
            raise ConfessionNotFoundError()
        return confession

    async def stats(self, confession_id: str) -> ConfessionStats:
        average, count = await self.confessions.rating_summary(confession_id)
        bookmarks = await self.confessions.bookmark_count(confession_id)
        confession = await self.confessions.get_by_id(confession_id)
        return ConfessionStats(
            average_rating=average,
            rating_count=count,
            bookmark_count=bookmarks,
            reply_count=confession.reply_count if confession else 0,
        )

    async def build_view(self, confession: Confession) -> ConfessionView:
        """Assemble everything an embed needs in one place."""
        alias = await self.aliases.get(confession.alias_id)
        guild_settings = await self.guilds.get_settings(confession.guild_id)
        scale_max = guild_settings.rating_scale_max if guild_settings else 5

        parent_number = None
        if confession.parent_confession_id:
            parent = await self.confessions.get_by_id(confession.parent_confession_id)
            parent_number = parent.public_number if parent else None

        updates = await self.confessions.get_child_updates(confession.id)

        # Poll results travel with the confession so the embed and its vote
        # buttons are always rendered from a single consistent snapshot.
        from app.services.poll_service import PollService

        poll_view = await PollService(self.session).get_for_confession(confession.id)

        return ConfessionView(
            confession_id=confession.id,
            guild_id=confession.guild_id,
            public_number=confession.public_number,
            alias_display=format_alias(alias.public_alias) if alias else "Anon",
            alias_id=confession.alias_id,
            content=confession.content,
            created_at=confession.created_at,
            stats=await self.stats(confession.id),
            scale_max=scale_max,
            parent_number=parent_number,
            parent_confession_id=confession.parent_confession_id,
            update_numbers=[update.public_number for update in updates],
            latest_update_id=updates[-1].id if updates else None,
            has_poll=poll_view is not None,
            poll=poll_view,
            message_link=confession.message_link(),
        )

    async def preview_rows(self, confessions: list[Confession]) -> list[tuple[int, str]]:
        """``(public_number, one-line preview)`` pairs for list embeds."""
        return [(item.public_number, one_line(item.content, 60)) for item in confessions]

    # --- Removal -----------------------------------------------------------

    async def remove(
        self, confession_id: str, *, moderator_id: int | None, reason: str | None
    ) -> Confession:
        """Soft delete. The row survives for audit; the message is pulled by the caller."""
        confession = await self.get(confession_id)
        previous = {"status": str(confession.status), "is_deleted": confession.is_deleted}

        await self.confessions.mark_deleted(
            confession_id, moderator_id=moderator_id, reason=reason
        )
        await self.ledger.record(
            LedgerAction.CONFESSION_REMOVED,
            internal_user_id=confession.internal_user_id,
            guild_id=confession.guild_id,
            confession_id=confession.id,
            moderator_id=moderator_id,
            reason=reason,
            previous_state=previous,
            new_state={"status": ConfessionStatus.REMOVED.value, "is_deleted": True},
        )
        await self.session.refresh(confession)
        return confession

    async def register_reply(self, message_id: int) -> Confession | None:
        """Count a Discord reply toward the 'most discussed' metric."""
        confession = await self.confessions.get_by_message_id(message_id)
        if confession is None or confession.is_deleted:
            return None
        await self.confessions.increment_reply_count(confession.id)
        return confession

    async def chain_summary(self, confession_id: str) -> list[tuple[int, str, bool]]:
        """The original and every update, in order, for the ``View Updates`` screen.

        Returns ``(public_number, preview, is_the_one_you_clicked)`` so the UI can
        mark the reader's current position in the story.
        """
        confession = await self.get_visible(confession_id)
        chain = await self.confessions.list_chain(
            confession.root_confession_id or confession.id
        )
        return [
            (item.public_number, one_line(item.content, 70), item.id == confession_id)
            for item in chain
            if not item.is_deleted
        ]
