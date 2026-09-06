"""Application configuration.

All configuration is environment driven. Nothing server specific is ever
hard-coded here: values in this module are *defaults* used when a guild has not
overridden them in ``guild_settings``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Root settings object, loaded from environment / ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Discord -----------------------------------------------------------
    discord_token: str = ""
    #: Parsed from a comma-separated string. This is the *only* place bot owner
    #: ids exist - nothing in the source hard-codes them.
    #: ``NoDecode`` stops pydantic-settings trying to JSON-parse the raw
    #: environment value, so the validator below sees the plain string and a
    #: malformed value produces a readable startup error, not a traceback.
    bot_owner_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)

    # --- Database ----------------------------------------------------------
    database_url: str = "sqlite+aiosqlite:///./hush.sqlite3"
    database_echo: bool = False
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # --- Runtime -----------------------------------------------------------
    environment: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool = False

    # --- Branding ----------------------------------------------------------
    brand_name: str = "Hush"
    brand_tagline: str = "Anonymous confessions made simple."
    #: Shown on every public confession. Deliberately does not promise that a
    #: user is untraceable - Hush retains account mappings for moderation.
    brand_privacy_note: str = "Anonymous to regular server members."

    # --- Public links (optional; buttons only render when set) --------------
    support_server_url: str | None = None
    github_url: str | None = None
    privacy_policy_url: str | None = None
    terms_url: str | None = None

    #: Apply pending migrations during startup. On by default so a Railway
    #: deploy is a single step; turn off if you run migrations separately.
    run_migrations_on_start: bool = True

    #: Overrides app.__version__ only if explicitly set. Normally left blank so
    #: the Python module stays the single source of truth.
    hush_version: str | None = None

    # --- Directories -------------------------------------------------------
    backup_directory: Path = Path("./backups")
    export_directory: Path = Path("./exports")
    log_directory: Path = Path("./logs")

    # --- Product defaults (per-guild overridable) --------------------------
    rules_version: int = 1
    default_confession_limit: int = 1500
    default_alias_rotation_days: int = 14
    rating_scale_min: int = 1
    rating_scale_max: int = 5
    trending_limit: int = 7
    trending_window_hours: int = 24

    # --- Retention ---------------------------------------------------------
    draft_expiry_minutes: int = 30
    export_retention_hours: int = 24
    notification_max_attempts: int = 3

    # --- Backups -----------------------------------------------------------
    backup_enabled: bool = True
    backup_hourly_retention_hours: int = 48
    backup_daily_retention_days: int = 30
    backup_weekly_retention_days: int = 180

    # --- Abuse control -----------------------------------------------------
    rate_limit_confessions_per_hour: int = 5
    rate_limit_reports_per_hour: int = 10
    rate_limit_interactions_per_minute: int = 40

    @field_validator("bot_owner_ids", mode="before")
    @classmethod
    def _split_owner_ids(cls, value: object) -> object:
        """Accept ``"1,2,3"``, a JSON list, an empty string, or a real list.

        An empty or malformed value yields an empty list rather than raising, so
        a misconfigured deploy reaches the startup validator and gets a readable
        message instead of a pydantic traceback.
        """
        if value is None:
            return []
        if isinstance(value, str):
            text = value.strip().strip("[]")
            if not text:
                return []
            ids: list[int] = []
            for part in text.replace('"', "").replace("'", "").split(","):
                part = part.strip()
                if part.isdigit():
                    ids.append(int(part))
            return ids
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalise_database_url(cls, value: object) -> object:
        """Accept the plain ``postgresql://`` URL that hosts like Railway provide.

        SQLAlchemy needs an async driver. Rather than making every operator
        remember to rewrite the scheme, upgrade it here.
        """
        if isinstance(value, str):
            if value.startswith("postgres://"):
                return "postgresql+asyncpg://" + value[len("postgres://"):]
            if value.startswith("postgresql://"):
                return "postgresql+asyncpg://" + value[len("postgresql://"):]
        return value

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"invalid log level: {value}")
        return level

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def ensure_directories(self) -> None:
        """Create the runtime directories the bot writes into."""
        for directory in (self.backup_directory, self.export_directory, self.log_directory):
            directory.mkdir(parents=True, exist_ok=True)

    @property
    def version(self) -> str:
        """The running version, from the centralized module unless overridden."""
        from app.__version__ import __version__

        return (self.hush_version or "").strip() or __version__

    @property
    def links(self) -> dict[str, str]:
        """Configured public links only. Blank values are treated as unset, so
        the About page never renders a button that goes nowhere."""
        candidates = {
            "Support": self.support_server_url,
            "GitHub": self.github_url,
            "Privacy": self.privacy_policy_url,
            "Terms": self.terms_url,
        }
        return {
            label: url.strip()
            for label, url in candidates.items()
            if url and url.strip().startswith(("http://", "https://"))
        }

    def validate_for_startup(self) -> list[str]:
        """Return a list of fatal configuration problems.

        Returning problems rather than raising lets the caller report *all* of
        them at once, so an operator fixes one deploy instead of three.
        """
        problems: list[str] = []

        if not self.discord_token.strip():
            problems.append("DISCORD_TOKEN is not set.")
        if not self.database_url.strip():
            problems.append("DATABASE_URL is not set.")
        if not self.bot_owner_ids:
            problems.append(
                "BOT_OWNER_IDS is empty - no one would be able to run owner commands."
            )
        if self.is_production and self.is_sqlite:
            problems.append(
                "ENVIRONMENT=production with a SQLite DATABASE_URL. "
                "Production needs PostgreSQL; SQLite will not survive a redeploy."
            )
        if self.default_confession_limit < 50:
            problems.append("DEFAULT_CONFESSION_LIMIT is too small to be usable.")

        return problems

    def safe_dump(self) -> dict[str, object]:
        """Configuration snapshot with every secret removed (safe to log)."""
        data = self.model_dump(mode="json")
        data.pop("discord_token", None)
        data["database_url"] = _redact_dsn(self.database_url)
        return data


def _redact_dsn(dsn: str) -> str:
    """Strip credentials out of a database URL so it can be logged."""
    if "@" not in dsn or "://" not in dsn:
        return dsn
    scheme, remainder = dsn.split("://", 1)
    _credentials, host = remainder.rsplit("@", 1)
    return f"{scheme}://***@{host}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
