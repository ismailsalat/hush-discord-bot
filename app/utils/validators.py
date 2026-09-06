"""Input validation shared by services and the Discord layer."""

from __future__ import annotations

from app.core.exceptions import ConfessionEmptyError, ConfessionTooLongError, InvalidPollError
from app.utils.text import normalize_confession

MIN_CONFESSION_LENGTH = 1
MAX_POLL_OPTIONS = 4
MIN_POLL_OPTIONS = 2
MAX_POLL_QUESTION_LENGTH = 200
MAX_POLL_OPTION_LENGTH = 80


def validate_confession(raw: str, limit: int) -> str:
    """Normalise and length-check a confession. Returns the cleaned text."""
    text = normalize_confession(raw)
    if len(text) < MIN_CONFESSION_LENGTH:
        raise ConfessionEmptyError()
    if len(text) > limit:
        raise ConfessionTooLongError(len(text), limit)
    return text


def validate_poll(question: str, options: list[str]) -> tuple[str, list[str]]:
    """Validate a poll question and its options."""
    cleaned_question = " ".join((question or "").split())
    if not cleaned_question:
        raise InvalidPollError("poll question is empty", user_message="Your poll needs a question.")
    if len(cleaned_question) > MAX_POLL_QUESTION_LENGTH:
        raise InvalidPollError(
            "poll question too long",
            user_message=f"Poll questions must be {MAX_POLL_QUESTION_LENGTH} characters or fewer.",
        )

    cleaned_options = [" ".join(option.split()) for option in options if option and option.strip()]
    if len(cleaned_options) < MIN_POLL_OPTIONS:
        raise InvalidPollError(
            "too few options", user_message=f"A poll needs at least {MIN_POLL_OPTIONS} options."
        )
    if len(cleaned_options) > MAX_POLL_OPTIONS:
        raise InvalidPollError(
            "too many options", user_message=f"A poll can have at most {MAX_POLL_OPTIONS} options."
        )
    if len({option.lower() for option in cleaned_options}) != len(cleaned_options):
        raise InvalidPollError("duplicate options", user_message="Poll options must be different.")
    for option in cleaned_options:
        if len(option) > MAX_POLL_OPTION_LENGTH:
            raise InvalidPollError(
                "option too long",
                user_message=f"Poll options must be {MAX_POLL_OPTION_LENGTH} characters or fewer.",
            )
    return cleaned_question, cleaned_options


def validate_reason(raw: str | None, *, max_length: int = 500, required: bool = True) -> str:
    """Validate a moderator-supplied reason string."""
    text = " ".join((raw or "").split())
    if required and not text:
        raise InvalidPollError("reason required", user_message="A reason is required.")
    return text[:max_length]
