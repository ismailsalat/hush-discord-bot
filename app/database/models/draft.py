"""Short-lived confession drafts.

A draft exists so a failed post never costs someone their text. One live draft
per user per guild keeps the recovery UI unambiguous.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, IdType, Snowflake, TimestampMixin
from app.security.identifiers import new_id
from app.utils.time import is_expired


class Draft(Base, TimestampMixin):
    __tablename__ = "drafts"
    __table_args__ = (
        UniqueConstraint("internal_user_id", "guild_id", name="uq_draft_user_guild"),
        Index("ix_draft_expires", "expires_at"),
    )

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=lambda: new_id("drf_"))
    internal_user_id: Mapped[str] = mapped_column(
        IdType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    guild_id: Mapped[int] = mapped_column(
        Snowflake, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)

    #: Set when the draft is an update to an existing confession.
    parent_confession_id: Mapped[str | None] = mapped_column(
        IdType, ForeignKey("confessions.id", ondelete="SET NULL"), default=None
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)

    @property
    def is_expired(self) -> bool:
        return is_expired(self.expires_at)
