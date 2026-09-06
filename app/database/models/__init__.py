"""Every mapped model. Importing this module registers all mappers.

Alembic's autogenerate and ``Database.create_all`` both rely on this being the
single place that knows about the full schema.
"""

from app.database.models.agreement import Agreement
from app.database.models.alias import AnonAlias
from app.database.models.audit import ExportRecord, SystemEvent
from app.database.models.bookmark import Bookmark
from app.database.models.confession import Confession
from app.database.models.draft import Draft
from app.database.models.follow import Follow
from app.database.models.guild import Guild, GuildSettings
from app.database.models.moderation import Ban, ModerationLedger, ModerationWarning
from app.database.models.notification import Notification
from app.database.models.poll import Poll, PollOption, PollVote
from app.database.models.rating import Rating
from app.database.models.report import Report
from app.database.models.user import GuildMembership, User

__all__ = [
    "Agreement",
    "AnonAlias",
    "Ban",
    "Bookmark",
    "Confession",
    "Draft",
    "ExportRecord",
    "Follow",
    "Guild",
    "GuildMembership",
    "GuildSettings",
    "ModerationLedger",
    "ModerationWarning",
    "Notification",
    "Poll",
    "PollOption",
    "PollVote",
    "Rating",
    "Report",
    "SystemEvent",
    "User",
]
