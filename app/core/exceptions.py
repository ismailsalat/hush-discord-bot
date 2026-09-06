"""Domain exception hierarchy.

Every exception carries a ``user_message`` that is safe to show in Discord.
The presentation layer maps these onto embeds; it never shows raw tracebacks.
"""

from __future__ import annotations

from datetime import datetime


class HushError(Exception):
    """Base class for every expected, domain-level failure."""

    user_title = "Something went wrong"
    user_message = "That action could not be completed right now. Please try again."
    #: When true the error is expected business logic, not a bug worth alerting on.
    expected = True

    def __init__(self, message: str | None = None, *, user_message: str | None = None):
        super().__init__(message or self.__class__.user_message)
        if user_message is not None:
            self.user_message = user_message


# --- Access / gating -------------------------------------------------------


class AgreementRequiredError(HushError):
    user_title = "One quick step first"
    user_message = "Please accept the confession rules before continuing."


class UserHushBannedError(HushError):
    user_title = "Hush access suspended"
    user_message = "You currently cannot use Hush in this server."

    def __init__(self, *, expires_at: datetime | None = None, reason: str | None = None,
                 permanent: bool = False):
        self.expires_at = expires_at
        self.reason = reason
        self.permanent = permanent
        super().__init__("user is banned from Hush")


class PendingModerationNoticeError(HushError):
    user_title = "You have a new notice"
    user_message = "You have a moderation notice waiting. Please review it first."

    def __init__(self, notification_id: str):
        self.notification_id = notification_id
        super().__init__("blocking moderation notice pending")


class PermissionDeniedError(HushError):
    user_title = "Not allowed"
    user_message = "You do not have permission to do that."


class ExportPermissionError(PermissionDeniedError):
    user_message = "You do not have permission to export this data."


# --- Configuration ---------------------------------------------------------


class GuildOnlyError(HushError):
    """Raised when a server-scoped command is used outside a server."""

    expected = True
    user_title = "Use this in a server"

    def __init__(self) -> None:
        super().__init__(
            "guild-only command used in DM",
            user_message="This command works inside a Discord server.",
        )


class DMOnlyError(HushError):
    """Raised when a private user command is invoked from a server."""

    expected = True
    user_title = "Use this in Hush DMs"

    def __init__(self) -> None:
        super().__init__(
            "DM-only command used in guild",
            user_message=(
                "For privacy, this command only works in your direct messages with Hush. "
                "Open Hush's profile and choose **Message**."
            ),
        )


class GuildNotConfiguredError(HushError):
    user_title = "Not set up yet"
    user_message = "Hush has not been set up in this server yet. An administrator needs to run `/admin setup`."


class FeatureDisabledError(HushError):
    user_title = "Unavailable"
    user_message = "That feature is turned off in this server."


class MissingChannelPermissionsError(HushError):
    user_title = "Missing permissions"
    user_message = "Hush cannot post in the confession channel."

    def __init__(self, channel_mention: str, missing: list[str]):
        self.channel_mention = channel_mention
        self.missing = missing
        super().__init__(f"missing permissions in {channel_mention}: {missing}")


# --- Confessions -----------------------------------------------------------


class ConfessionNotFoundError(HushError):
    user_title = "Unavailable"
    user_message = "This confession is no longer available."


class ConfessionTooLongError(HushError):
    user_title = "A little too long"

    def __init__(self, length: int, limit: int):
        self.length = length
        self.limit = limit
        super().__init__(
            f"confession is {length} characters, limit is {limit}",
            user_message=(
                f"Your confession is {length:,} characters, but the limit here is {limit:,}. "
                "Edit it down and it is ready to go - nothing was lost."
            ),
        )


class ConfessionEmptyError(HushError):
    user_title = "Nothing to post"
    user_message = "Your confession appears to be empty. Add some text and try again."


class DuplicateSubmissionError(HushError):
    user_title = "Already posted"
    user_message = "That confession was already posted."


class UpdatesDisabledError(FeatureDisabledError):
    user_message = "Confession updates are turned off in this server."


class NotConfessionAuthorError(PermissionDeniedError):
    user_message = "Only the author of that confession can do this."


# --- Aliases ---------------------------------------------------------------


class AliasRotationCooldownError(HushError):
    user_title = "Not yet"

    def __init__(self, available_at: datetime):
        self.available_at = available_at
        super().__init__(
            "alias rotation still on cooldown",
            user_message="You cannot change your anonymous ID yet.",
        )


class AliasPoolExhaustedError(HushError):
    user_message = "No anonymous IDs are available in this server right now. Please contact an administrator."
    expected = False


class AliasNotFoundError(HushError):
    user_title = "Unavailable"
    user_message = "That anonymous profile is not available."


# --- Engagement ------------------------------------------------------------


class AlreadyFollowingError(HushError):
    user_message = "You already follow this anonymous profile."


class NotFollowingError(HushError):
    user_message = "You are not following this anonymous profile."


class CannotFollowSelfError(HushError):
    user_message = "You cannot follow your own anonymous profile."


class AlreadyBookmarkedError(HushError):
    user_message = "You already saved this confession."


class InvalidRatingError(HushError):
    def __init__(self, low: int, high: int):
        super().__init__(
            "rating out of range",
            user_message=f"Ratings must be between {low} and {high}.",
        )


class AlreadyReportedError(HushError):
    user_title = "Already reported"
    user_message = "You already reported this confession. Moderators are reviewing it."


class PollAlreadyExistsError(HushError):
    user_message = "This confession already has a poll."


class PollNotFoundError(HushError):
    user_title = "Unavailable"
    user_message = "That poll is no longer available."


class InvalidPollError(HushError):
    pass


# --- Abuse -----------------------------------------------------------------


class RateLimitedError(HushError):
    user_title = "Slow down a moment"

    def __init__(self, retry_after_seconds: int, what: str = "that"):
        self.retry_after_seconds = retry_after_seconds
        minutes = max(1, round(retry_after_seconds / 60))
        super().__init__(
            "rate limited",
            user_message=f"You are doing {what} a little too quickly. Try again in about {minutes} minute(s).",
        )


# --- Infrastructure --------------------------------------------------------


class DatabaseOperationError(HushError):
    user_title = "Something went wrong"
    user_message = "A database problem stopped that action. Your work was saved where possible."
    expected = False


class NotificationDeliveryError(HushError):
    user_message = "The notification could not be delivered."
    expected = False


class BackupError(HushError):
    user_message = "The backup operation failed."
    expected = False


class BackupVerificationError(BackupError):
    user_message = "The backup failed verification."


class ExportError(HushError):
    user_message = "The export could not be generated."
    expected = False
