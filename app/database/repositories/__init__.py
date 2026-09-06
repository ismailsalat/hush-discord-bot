"""Repositories own all SQL. Services orchestrate; cogs only talk to services."""

from app.database.repositories.aliases import AliasRepository
from app.database.repositories.bookmarks import BookmarkRepository
from app.database.repositories.confessions import ConfessionRepository
from app.database.repositories.drafts import DraftRepository
from app.database.repositories.exports import ExportRepository
from app.database.repositories.follows import FollowRepository
from app.database.repositories.guilds import GuildRepository
from app.database.repositories.moderation import ModerationRepository
from app.database.repositories.notifications import NotificationRepository
from app.database.repositories.polls import PollRepository
from app.database.repositories.ratings import RatingRepository
from app.database.repositories.reports import ReportRepository
from app.database.repositories.users import UserRepository

__all__ = [
    "AliasRepository",
    "BookmarkRepository",
    "ConfessionRepository",
    "DraftRepository",
    "ExportRepository",
    "FollowRepository",
    "GuildRepository",
    "ModerationRepository",
    "NotificationRepository",
    "PollRepository",
    "RatingRepository",
    "ReportRepository",
    "UserRepository",
]
