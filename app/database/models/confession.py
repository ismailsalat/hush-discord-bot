"""Confessions.

Two identifiers exist on purpose:

``id``             immutable random primary key (``conf_...``) used everywhere
                   internally and inside Discord component custom ids.
``public_number``  the friendly per-guild counter shown to humans (``#184``).

The public number is never a foreign key, so it can never be used to walk the
table or infer volume across guilds.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import ConfessionStatus
from app.database.base import Base, IdType, Snowflake, TimestampMixin, enum_column
from app.security.identifiers import new_confession_id


class Confession(Base, TimestampMixin):
    __tablename__ = "confessions"
    __table_args__ = (
        UniqueConstraint("guild_id", "public_number", name="uq_confession_guild_number"),
        UniqueConstraint("idempotency_key", name="uq_confession_idempotency"),
        Index("ix_confession_guild_status", "guild_id", "status"),
        Index("ix_confession_alias", "alias_id"),
        Index("ix_confession_root", "root_confession_id"),
        Index("ix_confession_guild_created", "guild_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=new_confession_id)
    guild_id: Mapped[int] = mapped_column(
        Snowflake, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False
    )
    public_number: Mapped[int] = mapped_column(nullable=False)

    internal_user_id: Mapped[str] = mapped_column(
        IdType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alias_id: Mapped[str] = mapped_column(
        IdType, ForeignKey("anon_aliases.id", ondelete="RESTRICT"), nullable=False
    )

    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_fingerprint: Mapped[str | None] = mapped_column(String(64), default=None, index=True)

    status: Mapped[ConfessionStatus] = mapped_column(
        enum_column(ConfessionStatus), default=ConfessionStatus.PENDING, nullable=False
    )

    # --- Discord placement --------------------------------------------------
    discord_message_id: Mapped[int | None] = mapped_column(Snowflake, default=None, index=True)
    discord_channel_id: Mapped[int | None] = mapped_column(Snowflake, default=None)

    # --- Update chain -------------------------------------------------------
    parent_confession_id: Mapped[str | None] = mapped_column(
        IdType, ForeignKey("confessions.id", ondelete="SET NULL"), default=None
    )
    root_confession_id: Mapped[str | None] = mapped_column(IdType, default=None)

    # --- Denormalised engagement counter -----------------------------------
    #: Replies are counted from Discord message references; ratings and
    #: bookmarks are aggregated from their own tables so they cannot drift.
    reply_count: Mapped[int] = mapped_column(default=0, nullable=False)

    # --- Soft delete --------------------------------------------------------
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    deleted_by: Mapped[int | None] = mapped_column(Snowflake, default=None)
    delete_reason: Mapped[str | None] = mapped_column(String(500), default=None)

    #: Set by the client before posting so a double-click cannot create two rows.
    idempotency_key: Mapped[str | None] = mapped_column(String(64), default=None)

    @property
    def is_visible(self) -> bool:
        return not self.is_deleted and self.status == ConfessionStatus.POSTED

    @property
    def is_update(self) -> bool:
        return self.parent_confession_id is not None

    def message_link(self) -> str | None:
        if not (self.discord_message_id and self.discord_channel_id):
            return None
        return (
            f"https://discord.com/channels/{self.guild_id}/"
            f"{self.discord_channel_id}/{self.discord_message_id}"
        )
