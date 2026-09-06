"""Shared enumerations and constant values."""

from __future__ import annotations

from enum import StrEnum


class ConfessionStatus(StrEnum):
    """Lifecycle of a confession row.

    ``PENDING`` exists so the database never disagrees with Discord: the row is
    written first, the message is posted second, and reconciliation repairs any
    row that never reached ``POSTED``.
    """

    PENDING = "PENDING"
    POSTED = "POSTED"
    FAILED = "FAILED"
    REMOVED = "REMOVED"


class ReportReason(StrEnum):
    SELF_HARM = "SELF_HARM"
    SEXUAL_ASSAULT = "SEXUAL_ASSAULT"
    MINOR_SEXUAL_CONTENT = "MINOR_SEXUAL_CONTENT"
    THREATS = "THREATS"
    DOXXING = "DOXXING"
    HARASSMENT = "HARASSMENT"
    GRAPHIC = "GRAPHIC"
    OTHER = "OTHER"

    @property
    def label(self) -> str:
        return _REPORT_LABELS[self]


_REPORT_LABELS: dict[ReportReason, str] = {
    ReportReason.SELF_HARM: "Prohibited self-harm content",
    ReportReason.SEXUAL_ASSAULT: "Sexual assault content",
    ReportReason.MINOR_SEXUAL_CONTENT: "Sexual content involving minors",
    ReportReason.THREATS: "Credible threats",
    ReportReason.DOXXING: "Doxxing / private information",
    ReportReason.HARASSMENT: "Severe targeted harassment",
    ReportReason.GRAPHIC: "Extremely graphic content",
    ReportReason.OTHER: "Other",
}


class ReportStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class NotificationKind(StrEnum):
    WARNING = "WARNING"
    BAN = "BAN"
    BAN_REVOKED = "BAN_REVOKED"
    CONFESSION_REMOVED = "CONFESSION_REMOVED"
    FOLLOW_NEW_CONFESSION = "FOLLOW_NEW_CONFESSION"


class NotificationStatus(StrEnum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class LedgerAction(StrEnum):
    RULES_ACCEPTED = "RULES_ACCEPTED"
    RULES_REACCEPTED = "RULES_REACCEPTED"

    CONFESSION_CREATED = "CONFESSION_CREATED"
    CONFESSION_REMOVED = "CONFESSION_REMOVED"

    WARNING_CREATED = "WARNING_CREATED"
    WARNING_ACKNOWLEDGED = "WARNING_ACKNOWLEDGED"
    WARNING_REVOKED = "WARNING_REVOKED"

    TEMP_BAN_CREATED = "TEMP_BAN_CREATED"
    TEMP_BAN_EXPIRED = "TEMP_BAN_EXPIRED"
    PERMANENT_BAN_CREATED = "PERMANENT_BAN_CREATED"
    BAN_REVOKED = "BAN_REVOKED"

    ALIAS_CREATED = "ALIAS_CREATED"
    ALIAS_ROTATED = "ALIAS_ROTATED"

    REPORT_CREATED = "REPORT_CREATED"
    REPORT_RESOLVED = "REPORT_RESOLVED"

    EXPORT_CREATED = "EXPORT_CREATED"
    IDENTITY_LOOKUP = "IDENTITY_LOOKUP"
    CONFIG_CHANGED = "CONFIG_CHANGED"


class PermissionLevel(StrEnum):
    """Ordered permission tiers. Compare with :meth:`meets`.

    ``MODERATOR`` and ``ADMIN`` are *Hush* roles configured per guild, not
    Discord permissions: a server owner can trust someone with Hush without
    granting them Discord Administrator.
    """

    USER = "USER"
    MODERATOR = "MODERATOR"
    ADMIN = "ADMIN"
    SERVER_OWNER = "SERVER_OWNER"
    BOT_OWNER = "BOT_OWNER"

    @property
    def rank(self) -> int:
        return _PERMISSION_RANK[self]

    def meets(self, required: "PermissionLevel") -> bool:
        return self.rank >= required.rank

    @property
    def label(self) -> str:
        return _PERMISSION_LABEL[self]


_PERMISSION_RANK: dict[PermissionLevel, int] = {
    PermissionLevel.USER: 0,
    PermissionLevel.MODERATOR: 10,
    PermissionLevel.ADMIN: 20,
    PermissionLevel.SERVER_OWNER: 30,
    PermissionLevel.BOT_OWNER: 40,
}

_PERMISSION_LABEL: dict[PermissionLevel, str] = {
    PermissionLevel.USER: "Member",
    PermissionLevel.MODERATOR: "Hush Moderator",
    PermissionLevel.ADMIN: "Hush Admin",
    PermissionLevel.SERVER_OWNER: "Server Owner",
    PermissionLevel.BOT_OWNER: "Bot Owner",
}


class ExportScope(StrEnum):
    FULL = "FULL"
    GUILD = "GUILD"
    USER = "USER"
    ALIAS = "ALIAS"
    CONFESSION = "CONFESSION"
    MODERATION = "MODERATION"
    CONFESSIONS_ONLY = "CONFESSIONS_ONLY"
    REPORTS_ONLY = "REPORTS_ONLY"


class ExportFormat(StrEnum):
    JSON = "JSON"
    CSV = "CSV"
    TXT = "TXT"
    ZIP = "ZIP"


class BanDuration(StrEnum):
    HOUR = "HOUR"
    DAY = "DAY"
    WEEK = "WEEK"
    MONTH = "MONTH"
    PERMANENT = "PERMANENT"

    @property
    def hours(self) -> int | None:
        return _BAN_HOURS[self]

    @property
    def label(self) -> str:
        return _BAN_LABELS[self]


_BAN_HOURS: dict[BanDuration, int | None] = {
    BanDuration.HOUR: 1,
    BanDuration.DAY: 24,
    BanDuration.WEEK: 24 * 7,
    BanDuration.MONTH: 24 * 30,
    BanDuration.PERMANENT: None,
}

_BAN_LABELS: dict[BanDuration, str] = {
    BanDuration.HOUR: "1 hour",
    BanDuration.DAY: "24 hours",
    BanDuration.WEEK: "7 days",
    BanDuration.MONTH: "30 days",
    BanDuration.PERMANENT: "Permanent",
}
