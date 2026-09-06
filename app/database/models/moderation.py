"""Warnings, Hush feature bans, and the append-only moderation ledger."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import LedgerAction
from app.database.base import (
    Base,
    CreatedAtMixin,
    IdType,
    JSONType,
    Snowflake,
    TimestampMixin,
    enum_column,
)
from app.security.identifiers import new_id
from app.utils.time import is_expired


class ModerationWarning(Base, TimestampMixin):
    """Named ``ModerationWarning`` so it never shadows the builtin ``Warning``."""

    __tablename__ = "warnings"
    __table_args__ = (Index("ix_warning_user_guild", "internal_user_id", "guild_id"),)

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=lambda: new_id("wrn_"))
    internal_user_id: Mapped[str] = mapped_column(
        IdType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    guild_id: Mapped[int] = mapped_column(
        Snowflake, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False
    )
    moderator_id: Mapped[int] = mapped_column(Snowflake, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    related_confession_id: Mapped[str | None] = mapped_column(
        IdType, ForeignKey("confessions.id", ondelete="SET NULL"), default=None
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    revoked_by: Mapped[int | None] = mapped_column(Snowflake, default=None)

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class Ban(Base, TimestampMixin):
    """A Hush *feature* ban. It never touches Discord server membership."""

    __tablename__ = "bans"
    __table_args__ = (Index("ix_ban_user_guild_active", "internal_user_id", "guild_id"),)

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=lambda: new_id("ban_"))
    internal_user_id: Mapped[str] = mapped_column(
        IdType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    guild_id: Mapped[int] = mapped_column(
        Snowflake, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False
    )
    moderator_id: Mapped[int] = mapped_column(Snowflake, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    is_permanent: Mapped[bool] = mapped_column(default=False, nullable=False)

    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    revoked_by: Mapped[int | None] = mapped_column(Snowflake, default=None)

    @property
    def is_active(self) -> bool:
        """Active if not revoked and either permanent or not yet expired."""
        if self.revoked_at is not None:
            return False
        if self.is_permanent:
            return True
        return not is_expired(self.expires_at)


class ModerationLedger(Base, CreatedAtMixin):
    """Append-only audit trail.

    Rows are only ever inserted. Corrections are expressed as new rows, so the
    history can be replayed and never silently rewritten.
    """

    __tablename__ = "moderation_ledger"
    __table_args__ = (
        Index("ix_ledger_guild_created", "guild_id", "created_at"),
        Index("ix_ledger_user", "internal_user_id"),
        Index("ix_ledger_action", "action_type"),
    )

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=lambda: new_id("led_"))
    action_type: Mapped[LedgerAction] = mapped_column(enum_column(LedgerAction), nullable=False)

    internal_user_id: Mapped[str | None] = mapped_column(IdType, default=None)
    guild_id: Mapped[int | None] = mapped_column(Snowflake, default=None)
    moderator_id: Mapped[int | None] = mapped_column(Snowflake, default=None)
    confession_id: Mapped[str | None] = mapped_column(IdType, default=None)
    alias_id: Mapped[str | None] = mapped_column(IdType, default=None)

    reason: Mapped[str | None] = mapped_column(Text, default=None)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=None)
    previous_state: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=None)
    new_state: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=None)
