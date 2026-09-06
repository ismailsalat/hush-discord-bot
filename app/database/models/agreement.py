"""Rules acceptance records, versioned per guild."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, IdType, Snowflake
from app.security.identifiers import new_id
from app.utils.time import utcnow


class Agreement(Base):
    """A user accepting a specific rules version in a specific guild.

    Kept as one row per (user, guild, version) so raising ``rules_version``
    prompts exactly one re-acceptance instead of nagging on every confession.
    """

    __tablename__ = "agreements"
    __table_args__ = (
        UniqueConstraint(
            "internal_user_id", "guild_id", "agreement_version", name="uq_agreement_user_guild_version"
        ),
        Index("ix_agreement_lookup", "internal_user_id", "guild_id"),
    )

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=lambda: new_id("agr_"))
    internal_user_id: Mapped[str] = mapped_column(
        IdType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    guild_id: Mapped[int] = mapped_column(
        Snowflake, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False
    )
    agreement_version: Mapped[int] = mapped_column(nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None
