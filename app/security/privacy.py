"""Helpers that keep private data out of places it must not reach."""

from __future__ import annotations

import re
from typing import Any

#: Keys whose values are redacted before anything is logged or exported.
SENSITIVE_KEYS = frozenset(
    {
        "discord_token",
        "token",
        "password",
        "secret",
        "authorization",
        "api_key",
        "database_url",
    }
)

#: Keys that identify a real person; stripped from public-facing payloads.
IDENTITY_KEYS = frozenset({"discord_user_id", "internal_user_id", "voter_internal_user_id",
                           "follower_internal_user_id", "reporter_internal_user_id"})

REDACTED = "***"

_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{24,28}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}")


def scrub(value: Any) -> Any:
    """Recursively redact secrets from a structure destined for a log."""
    if isinstance(value, dict):
        return {
            key: REDACTED if key.lower() in SENSITIVE_KEYS else scrub(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return type(value)(scrub(item) for item in value)
    if isinstance(value, str):
        return _TOKEN_RE.sub(REDACTED, value)
    return value


def strip_identity(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove identity-linking keys from a dict shown to non-privileged viewers."""
    return {key: item for key, item in payload.items() if key not in IDENTITY_KEYS}


def anonymity_notice(brand: str = "Hush") -> str:
    """The single source of truth for our anonymity wording.

    We never claim absolute anonymity: the mapping exists and moderators can act
    on it. Saying so plainly is both honest and legally safer.
    """
    return (
        f"Anonymous to server members. {brand} retains account information for "
        "moderation and abuse prevention."
    )
