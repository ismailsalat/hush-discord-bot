"""Identifier generation and the public custom-id codec.

Two rules drive this module:

1. Every internal identifier is random and non-sequential. Nothing about a
   confession id, alias id or user id may hint at ordering, volume or identity.
2. Anything embedded in a Discord ``custom_id`` is publicly inspectable. Only
   opaque random ids ever go there - never a Discord user id, never an internal
   user id.
"""

from __future__ import annotations

import re
import secrets
import string
from dataclasses import dataclass

_HEX = "0123456789abcdef"

#: Ambiguous characters are excluded so aliases stay easy to read aloud/remember.
ALIAS_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"

USER_PREFIX = "usr_"
CONFESSION_PREFIX = "conf_"
ALIAS_PREFIX = "alias_"
GENERIC_PREFIX = "id_"


def _random_hex(length: int) -> str:
    return "".join(secrets.choice(_HEX) for _ in range(length))


def new_internal_user_id() -> str:
    """e.g. ``usr_72f48a20fe7c4f78``."""
    return f"{USER_PREFIX}{_random_hex(16)}"


def new_confession_id() -> str:
    """e.g. ``conf_f82c9d1a4b6e0357``."""
    return f"{CONFESSION_PREFIX}{_random_hex(16)}"


def new_alias_id() -> str:
    return f"{ALIAS_PREFIX}{_random_hex(16)}"


def new_id(prefix: str = "") -> str:
    """Generic random row id for supporting tables."""
    return f"{prefix}{_random_hex(16)}" if prefix else f"{GENERIC_PREFIX}{_random_hex(16)}"


def new_error_id() -> str:
    """Short, screenshot-friendly error reference such as ``ERR-X7B29``."""
    alphabet = string.ascii_uppercase + string.digits
    return "ERR-" + "".join(secrets.choice(alphabet) for _ in range(5))


def new_idempotency_key() -> str:
    return _random_hex(32)


# --- Public anonymous aliases ---------------------------------------------

#: Alias formats, tried in order. Each widens the pool when the previous fills.
ALIAS_FORMATS: tuple[tuple[int, int], ...] = (
    (1, 2),  # A17      -> 2,400 combinations
    (2, 2),  # AB17     -> 57,600
    (2, 3),  # AB170    -> 576,000
)


def generate_alias_candidate(tier: int = 0) -> str:
    """Return a random public alias body such as ``A17`` (no ``#`` prefix)."""
    letters, digits = ALIAS_FORMATS[min(tier, len(ALIAS_FORMATS) - 1)]
    letter_part = "".join(secrets.choice(ALIAS_LETTERS) for _ in range(letters))
    digit_part = "".join(secrets.choice(string.digits) for _ in range(digits))
    return f"{letter_part}{digit_part}"


ALIAS_RE = re.compile(r"^[A-Z]{1,2}[0-9]{2,3}$")


def normalize_alias(raw: str) -> str | None:
    """Accept ``a17``/``#A17``/``Anon #A17`` and return the canonical ``A17``."""
    if not raw:
        return None
    cleaned = raw.strip().upper().removeprefix("ANON").strip().lstrip("#").strip()
    return cleaned if ALIAS_RE.match(cleaned) else None


def format_alias(alias_body: str) -> str:
    """Public display form: ``Anon #A17``."""
    return f"Anon #{alias_body}"


# --- Discord custom_id codec ----------------------------------------------

CUSTOM_ID_NAMESPACE = "cf"
MAX_CUSTOM_ID_LENGTH = 100


@dataclass(frozen=True, slots=True)
class CustomId:
    """Parsed representation of a Hush component custom id."""

    action: str
    args: tuple[str, ...] = ()

    def encode(self) -> str:
        parts = [CUSTOM_ID_NAMESPACE, self.action, *self.args]
        encoded = ":".join(parts)
        if len(encoded) > MAX_CUSTOM_ID_LENGTH:
            raise ValueError(f"custom_id too long ({len(encoded)} > {MAX_CUSTOM_ID_LENGTH}): {encoded}")
        return encoded


#: Values that must never appear inside a publicly visible custom id.
_FORBIDDEN_IN_CUSTOM_ID = re.compile(r"\b\d{17,20}\b")


def build_custom_id(action: str, *args: str) -> str:
    """Build a namespaced custom id, refusing to embed identity data.

    Raises ``ValueError`` if a snowflake-looking value or an internal user id is
    passed. This is a deliberate tripwire: it turns a privacy leak into a loud
    failure during development rather than a silent one in production.
    """
    for arg in args:
        text = str(arg)
        if text.startswith(USER_PREFIX):
            raise ValueError("internal user ids must never appear in a custom_id")
        if _FORBIDDEN_IN_CUSTOM_ID.search(text):
            raise ValueError("Discord snowflakes must never appear in a custom_id")
    return CustomId(action, tuple(str(a) for a in args)).encode()


def parse_custom_id(raw: str) -> CustomId | None:
    """Parse a Hush custom id, or ``None`` if it is not one of ours."""
    parts = raw.split(":")
    if len(parts) < 2 or parts[0] != CUSTOM_ID_NAMESPACE:
        return None
    return CustomId(parts[1], tuple(parts[2:]))
