"""Queued outbound DMs.

Moderation notices are queued here *before* delivery is attempted. If a user has
DMs closed the row simply stays pending, and a blocking notice is replayed the
next time they touch Hush. Closing your DMs cannot make a punishment
notice disappear.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import NotificationKind, NotificationStatus
from app.database.base import (
    Base,
    IdType,
    JSONType,
    Snowflake,
    TimestampMixin,
    enum_column,
)
from app.security.identifiers import new_id


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notification_pending", "status", "created_at"),
        Index("ix_notification_user_blocking", "internal_user_id", "guild_id", "is_blocking"),
    )

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=lambda: new_id("ntf_"))
    internal_user_id: Mapped[str] = mapped_column(
        IdType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    guild_id: Mapped[int | None] = mapped_column(Snowflake, default=None)

    kind: Mapped[NotificationKind] = mapped_column(enum_column(NotificationKind), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)

    status: Mapped[NotificationStatus] = mapped_column(
        enum_column(NotificationStatus), default=NotificationStatus.PENDING, nullable=False
    )

    #: A blocking notice must be shown before the user may act again.
    is_blocking: Mapped[bool] = mapped_column(default=False, nullable=False)
    requires_acknowledgement: Mapped[bool] = mapped_column(default=False, nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    #: True once the content has been shown to the user by any route (DM or
    #: replayed in-app), which is what actually clears the block.
    shown_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    delivery_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    failure_reason: Mapped[str | None] = mapped_column(String(300), default=None)

    @property
    def is_outstanding(self) -> bool:
        """Still needs to be surfaced to the user."""
        if self.shown_at is None:
            return True
        return self.requires_acknowledgement and self.acknowledged_at is None
