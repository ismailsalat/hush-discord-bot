"""Convenience wrapper over the ledger plus durable system events."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import LedgerAction
from app.database.models import SystemEvent
from app.database.repositories import ModerationRepository
from app.logging.audit import log_metric


class AuditService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.ledger = ModerationRepository(session)

    async def record(self, action: LedgerAction, **fields: Any):
        return await self.ledger.record(action, **fields)

    async def config_changed(
        self,
        *,
        guild_id: int,
        moderator_id: int,
        previous: dict[str, Any],
        new: dict[str, Any],
        reason: str | None = None,
    ):
        return await self.ledger.record(
            LedgerAction.CONFIG_CHANGED,
            guild_id=guild_id,
            moderator_id=moderator_id,
            reason=reason,
            previous_state=previous,
            new_state=new,
        )

    async def system_event(
        self,
        event_type: str,
        *,
        level: str = "INFO",
        guild_id: int | None = None,
        message: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> SystemEvent:
        event = SystemEvent(
            event_type=event_type, level=level, guild_id=guild_id, message=message, meta=meta
        )
        self.session.add(event)
        await self.session.flush()
        log_metric(event_type, guild_id=guild_id)
        return event

    async def ledger_entries(
        self,
        *,
        guild_id: int | None = None,
        internal_user_id: str | None = None,
        action: LedgerAction | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ):
        return await self.ledger.list_ledger(
            guild_id=guild_id,
            internal_user_id=internal_user_id,
            action=action,
            since=since,
            limit=limit,
        )
