"""UTC-only time helpers. The application never stores naive local time."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def utcnow() -> datetime:
    """Timezone-aware current UTC time."""
    return datetime.now(UTC)


def ensure_utc(value: datetime | None) -> datetime | None:
    """Attach UTC to naive datetimes (SQLite round-trips lose tzinfo)."""
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def is_expired(value: datetime | None, *, now: datetime | None = None) -> bool:
    """True when ``value`` is in the past. ``None`` is treated as never expiring."""
    if value is None:
        return False
    return (ensure_utc(value) or value) <= (now or utcnow())


def in_hours(hours: float) -> datetime:
    return utcnow() + timedelta(hours=hours)


def in_minutes(minutes: float) -> datetime:
    return utcnow() + timedelta(minutes=minutes)


def in_days(days: float) -> datetime:
    return utcnow() + timedelta(days=days)


def discord_timestamp(value: datetime, style: str = "F") -> str:
    """Render a Discord dynamic timestamp so each user sees their own timezone."""
    return f"<t:{int((ensure_utc(value) or value).timestamp())}:{style}>"


def format_duration(delta: timedelta) -> str:
    """Human duration such as ``4d 7h`` or ``8 minutes``."""
    total = int(delta.total_seconds())
    if total < 60:
        return f"{total}s"
    minutes, seconds = divmod(total, 60)
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def format_date(value: datetime) -> str:
    """Static fallback date, e.g. ``September 14, 2026``."""
    return (ensure_utc(value) or value).strftime("%B %d, %Y").replace(" 0", " ")
