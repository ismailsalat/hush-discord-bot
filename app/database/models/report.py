"""User reports. Reporting never auto-removes anything - humans decide."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import ReportReason, ReportStatus
from app.database.base import Base, IdType, Snowflake, TimestampMixin, enum_column
from app.security.identifiers import new_id


class Report(Base, TimestampMixin):
    __tablename__ = "reports"
    __table_args__ = (
        # One report per person per confession: this is the primary defence
        # against report brigading, enforced by the database.
        UniqueConstraint(
            "confession_id", "reporter_internal_user_id", name="uq_report_confession_reporter"
        ),
        Index("ix_report_guild_status", "guild_id", "status"),
    )

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=lambda: new_id("rep_"))
    confession_id: Mapped[str] = mapped_column(
        IdType, ForeignKey("confessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reporter_internal_user_id: Mapped[str] = mapped_column(
        IdType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    guild_id: Mapped[int] = mapped_column(
        Snowflake, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False
    )

    reason: Mapped[ReportReason] = mapped_column(enum_column(ReportReason), nullable=False)
    details: Mapped[str | None] = mapped_column(Text, default=None)

    status: Mapped[ReportStatus] = mapped_column(
        enum_column(ReportStatus), default=ReportStatus.OPEN, nullable=False
    )
    resolved_by: Mapped[int | None] = mapped_column(Snowflake, default=None)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    resolution_note: Mapped[str | None] = mapped_column(String(500), default=None)
