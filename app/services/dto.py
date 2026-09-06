"""Plain data objects passed from services to the presentation layer.

Embeds and views never touch ORM instances directly, so rendering can never
trigger a lazy database load and can never accidentally read a private column.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ConfessionStats:
    average_rating: float | None
    rating_count: int
    bookmark_count: int
    reply_count: int

    @property
    def rating_display(self) -> str:
        if self.average_rating is None:
            return "Not yet rated"
        return f"{self.average_rating:.1f}"


@dataclass(frozen=True, slots=True)
class ConfessionView:
    """Everything needed to render one public confession embed."""

    confession_id: str
    guild_id: int
    public_number: int
    alias_display: str
    alias_id: str
    content: str
    created_at: datetime
    stats: ConfessionStats
    scale_max: int = 5

    parent_number: int | None = None
    parent_confession_id: str | None = None
    update_numbers: list[int] = field(default_factory=list)
    latest_update_id: str | None = None

    has_poll: bool = False
    poll: "PollView | None" = None
    message_link: str | None = None

    @property
    def is_update(self) -> bool:
        return self.parent_confession_id is not None


@dataclass(frozen=True, slots=True)
class ProfileView:
    """Public anonymous profile. Contains no link to a real identity."""

    alias_id: str
    alias_display: str
    guild_id: int
    is_current: bool
    confession_count: int
    average_rating: float | None
    rating_count: int
    follower_count: int
    most_rated_number: int | None
    most_rated_rating_count: int
    recent: list[tuple[int, str]] = field(default_factory=list)
    scale_max: int = 5

    @property
    def rating_display(self) -> str:
        if self.average_rating is None:
            return "Not yet rated"
        return f"{self.average_rating:.1f} / {self.scale_max}"


@dataclass(frozen=True, slots=True)
class PollOptionResult:
    option_id: str
    label: str
    votes: int
    percentage: float


@dataclass(frozen=True, slots=True)
class PollView:
    poll_id: str
    confession_id: str
    question: str
    options: list[PollOptionResult]
    total_votes: int
    is_open: bool
    voted_option_id: str | None = None


@dataclass(frozen=True, slots=True)
class TrendingEntry:
    confession_id: str
    public_number: int
    alias_display: str
    score: float
    average_rating: float | None
    rating_count: int
    reply_count: int
    preview: str


@dataclass(frozen=True, slots=True)
class HallOfFameEntry:
    confession_id: str
    public_number: int
    alias_display: str
    primary_metric: str
    preview: str


@dataclass(frozen=True, slots=True)
class HallOfFame:
    highest_rated: list[HallOfFameEntry]
    most_rated: list[HallOfFameEntry]
    most_discussed: list[HallOfFameEntry]


@dataclass(frozen=True, slots=True)
class PunishmentHistory:
    """Moderator-facing account history. Never includes the Discord identity."""

    alias_display: str
    warning_count: int
    active_warnings: int
    temp_ban_count: int
    permanent_ban_count: int
    is_currently_banned: bool
    removed_confession_count: int
    report_count: int
    entries: list[str] = field(default_factory=list)
