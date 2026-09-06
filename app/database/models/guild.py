"""Guild registration and per-guild configuration.

Nothing server-specific is ever hard-coded: every tunable lives here, seeded
from environment defaults the first time a guild is set up.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, JSONType, Snowflake, TimestampMixin


class Guild(Base, TimestampMixin):
    __tablename__ = "guilds"

    id: Mapped[int] = mapped_column(Snowflake, primary_key=True, autoincrement=False)
    name: Mapped[str | None] = mapped_column(String(120), default=None)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)


class GuildSettings(Base, TimestampMixin):
    """One configuration row per guild."""

    __tablename__ = "guild_settings"

    guild_id: Mapped[int] = mapped_column(
        Snowflake, ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True, autoincrement=False
    )

    # --- Channels and roles -------------------------------------------------
    confession_channel_id: Mapped[int | None] = mapped_column(Snowflake, default=None)
    mod_log_channel_id: Mapped[int | None] = mapped_column(Snowflake, default=None)
    # Hush roles are configured per guild so a server owner can delegate
    # without granting Discord Administrator. Users are supported alongside
    # roles because small servers often do not want a role for one person.
    admin_role_ids: Mapped[list[int]] = mapped_column(JSONType, default=list, nullable=False)
    admin_user_ids: Mapped[list[int]] = mapped_column(JSONType, default=list, nullable=False)
    moderator_role_ids: Mapped[list[int]] = mapped_column(JSONType, default=list, nullable=False)
    moderator_user_ids: Mapped[list[int]] = mapped_column(JSONType, default=list, nullable=False)

    # --- Agreement ----------------------------------------------------------
    rules_version: Mapped[int] = mapped_column(default=1, nullable=False)

    # --- Feature toggles ----------------------------------------------------
    ratings_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    followers_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    bookmarks_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    polls_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    updates_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    trending_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)

    # --- Limits -------------------------------------------------------------
    confession_character_limit: Mapped[int] = mapped_column(default=1500, nullable=False)
    alias_rotation_days: Mapped[int] = mapped_column(default=14, nullable=False)
    minimum_account_age_days: Mapped[int] = mapped_column(default=0, nullable=False)
    rating_scale_max: Mapped[int] = mapped_column(default=5, nullable=False)

    # --- Moderation behaviour ----------------------------------------------
    require_warning_acknowledgement: Mapped[bool] = mapped_column(default=True, nullable=False)

    @property
    def is_configured(self) -> bool:
        """A guild is usable once a confession channel has been chosen."""
        return self.confession_channel_id is not None

    def public_snapshot(self) -> dict[str, Any]:
        """Config values that are safe to show in an admin embed."""
        return {
            "confession_channel_id": self.confession_channel_id,
            "mod_log_channel_id": self.mod_log_channel_id,
            "rules_version": self.rules_version,
            "confession_character_limit": self.confession_character_limit,
            "alias_rotation_days": self.alias_rotation_days,
            "ratings_enabled": self.ratings_enabled,
            "followers_enabled": self.followers_enabled,
            "bookmarks_enabled": self.bookmarks_enabled,
            "polls_enabled": self.polls_enabled,
            "updates_enabled": self.updates_enabled,
        }
