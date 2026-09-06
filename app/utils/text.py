"""Text normalisation, sanitisation and Discord-safe formatting."""

from __future__ import annotations

import hashlib
import re
import unicodedata

#: Zero-width and bidi control characters used to smuggle hidden text.
_INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]")
_EXCESS_NEWLINES_RE = re.compile(r"\n{4,}")
_MENTION_RE = re.compile(r"@(everyone|here)")


def normalize_confession(raw: str) -> str:
    """Clean user submitted text without changing its meaning.

    Strips invisible characters, normalises unicode, collapses runaway blank
    lines and trims. Content itself is never altered or censored - human
    moderators decide what is acceptable.
    """
    text = unicodedata.normalize("NFC", raw or "")
    text = _INVISIBLE_RE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _EXCESS_NEWLINES_RE.sub("\n\n\n", text)
    return text.strip()


def neutralize_mentions(text: str) -> str:
    """Defuse ``@everyone``/``@here`` so a confession cannot ping a whole server.

    Discord's ``allowed_mentions`` is the real defence; this keeps the rendered
    text honest as well.
    """
    return _MENTION_RE.sub("@\u200b\\1", text)


def truncate(text: str, limit: int, suffix: str = "...") -> str:
    """Shorten to ``limit`` characters, never cutting mid-word when avoidable."""
    if len(text) <= limit:
        return text
    cut = text[: max(0, limit - len(suffix))]
    if " " in cut[-20:]:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip() + suffix


def one_line(text: str, limit: int = 80) -> str:
    """Flatten to a single line for list rows and previews."""
    return truncate(" ".join(text.split()), limit)


def escape_markdown(text: str) -> str:
    """Escape Discord markdown so quoted user text renders literally."""
    return re.sub(r"([*_`~|\\>])", r"\\\1", text)


def content_fingerprint(text: str) -> str:
    """Stable hash of normalised content, used to spot repeated confessions.

    Only the hash is stored for duplicate detection - never used to link users.
    """
    collapsed = " ".join(normalize_confession(text).lower().split())
    return hashlib.sha256(collapsed.encode("utf-8")).hexdigest()


def pluralize(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count:,} {singular if count == 1 else (plural or singular + 's')}"


def progress_bar(fraction: float, width: int = 12) -> str:
    """Unicode bar used for poll results."""
    filled = max(0, min(width, round(fraction * width)))
    return "\u2588" * filled + "\u2591" * (width - filled)
