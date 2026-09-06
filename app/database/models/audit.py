"""Export records and generic system events."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import ExportFormat, ExportScope
from app.database.base import (
    Base,
    CreatedAtMixin,
    IdType,
    JSONType,
    Snowflake,
    enum_column,
)
from app.security.identifiers import new_id
from app.utils.time import is_expired


class ExportRecord(Base, CreatedAtMixin):
    """Every export ever generated, who asked for it, and when it expires."""

    __tablename__ = "exports"
    __table_args__ = (Index("ix_export_expires", "expires_at"),)

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=lambda: new_id("exp_"))
    requested_by_discord_id: Mapped[int] = mapped_column(Snowflake, nullable=False, index=True)
    scope: Mapped[ExportScope] = mapped_column(enum_column(ExportScope), nullable=False)
    export_format: Mapped[ExportFormat] = mapped_column(enum_column(ExportFormat), nullable=False)

    guild_id: Mapped[int | None] = mapped_column(Snowflake, default=None)
    target: Mapped[str | None] = mapped_column(String(120), default=None)

    file_path: Mapped[str | None] = mapped_column(Text, default=None)
    size_bytes: Mapped[int | None] = mapped_column(default=None)
    row_counts: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=None)

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    @property
    def is_expired(self) -> bool:
        return is_expired(self.expires_at)


class SystemEvent(Base, CreatedAtMixin):
    """Durable record of operational events used by ``/admin health``."""

    __tablename__ = "system_events"
    __table_args__ = (Index("ix_system_event_type_created", "event_type", "created_at"),)

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=lambda: new_id("evt_"))
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    level: Mapped[str] = mapped_column(String(16), default="INFO", nullable=False)
    guild_id: Mapped[int | None] = mapped_column(Snowflake, default=None)
    message: Mapped[str | None] = mapped_column(Text, default=None)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=None)
