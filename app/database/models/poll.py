"""Optional polls attached to an existing confession."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, CreatedAtMixin, IdType, TimestampMixin
from app.security.identifiers import new_id


class Poll(Base, TimestampMixin):
    __tablename__ = "polls"
    __table_args__ = (UniqueConstraint("confession_id", name="uq_poll_confession"),)

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=lambda: new_id("pol_"))
    confession_id: Mapped[str] = mapped_column(
        IdType, ForeignKey("confessions.id", ondelete="CASCADE"), nullable=False
    )
    created_by_internal_user_id: Mapped[str] = mapped_column(
        IdType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    question: Mapped[str] = mapped_column(String(200), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # Always eager loaded: a poll is meaningless without its options, and
    # selectin loading keeps this safe under async (no implicit lazy IO).
    options: Mapped[list["PollOption"]] = relationship(
        back_populates="poll",
        cascade="all, delete-orphan",
        order_by="PollOption.position",
        lazy="selectin",
    )

    @property
    def is_open(self) -> bool:
        return self.closed_at is None


class PollOption(Base):
    __tablename__ = "poll_options"
    __table_args__ = (
        UniqueConstraint("poll_id", "position", name="uq_poll_option_position"),
    )

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=lambda: new_id("opt_"))
    poll_id: Mapped[str] = mapped_column(
        IdType, ForeignKey("polls.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    position: Mapped[int] = mapped_column(nullable=False)

    poll: Mapped[Poll] = relationship(back_populates="options")


class PollVote(Base, CreatedAtMixin):
    __tablename__ = "poll_votes"
    __table_args__ = (
        # One vote each; changing a vote updates this row.
        UniqueConstraint("poll_id", "voter_internal_user_id", name="uq_poll_vote_voter"),
        Index("ix_poll_vote_option", "option_id"),
    )

    id: Mapped[str] = mapped_column(IdType, primary_key=True, default=lambda: new_id("pvt_"))
    poll_id: Mapped[str] = mapped_column(
        IdType, ForeignKey("polls.id", ondelete="CASCADE"), nullable=False
    )
    option_id: Mapped[str] = mapped_column(
        IdType, ForeignKey("poll_options.id", ondelete="CASCADE"), nullable=False
    )
    voter_internal_user_id: Mapped[str] = mapped_column(
        IdType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
