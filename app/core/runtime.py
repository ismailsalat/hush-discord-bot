"""Shared runtime container.

One object holds the settings, database, embed builders and abuse guards, and
every cog and view reaches its dependencies through it. This is the alternative
to module-level global state: it is explicit, injectable and trivially faked in
tests.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.database.session import Database
from app.logging.error_ids import error_counter
from app.embeds.about import AboutEmbedBuilder
from app.embeds.admin import AdminEmbedBuilder
from app.embeds.agreement import AgreementEmbedBuilder
from app.embeds.confession import ConfessionEmbedBuilder
from app.embeds.errors import ErrorEmbedBuilder
from app.embeds.factory import EmbedFactory
from app.embeds.moderation import ModerationEmbedBuilder
from app.embeds.profile import ProfileEmbedBuilder
from app.security.rate_limits import InFlightGuard, InteractionGuard, RateLimiter, RateLimitRule
from app.services.backup_service import BackupService
from app.services.health_service import HealthService
from app.utils.time import utcnow

if TYPE_CHECKING:  # pragma: no cover
    from app.services.publishing_service import PublishingService


class Runtime:
    def __init__(self, settings: Settings, database: Database):
        self.settings = settings
        self.database = database
        self.started_at = utcnow()

        factory = EmbedFactory(settings)
        self.embeds = factory
        self.confession_embeds = ConfessionEmbedBuilder(factory)
        self.profile_embeds = ProfileEmbedBuilder(factory)
        self.agreement_embeds = AgreementEmbedBuilder(factory)
        self.moderation_embeds = ModerationEmbedBuilder(factory)
        self.error_embeds = ErrorEmbedBuilder(factory)
        self.admin_embeds = AdminEmbedBuilder(factory)
        self.about_embeds = AboutEmbedBuilder(factory)

        self.rate_limiter = RateLimiter()
        self.interaction_guard = InteractionGuard()
        self.in_flight = InFlightGuard()

        self.confession_rule = RateLimitRule(
            settings.rate_limit_confessions_per_hour, 3600, "posting confessions"
        )
        self.report_rule = RateLimitRule(
            settings.rate_limit_reports_per_hour, 3600, "reporting"
        )
        self.interaction_rule = RateLimitRule(
            settings.rate_limit_interactions_per_minute, 60, "that"
        )

        #: Shared with the error reporter so /admin status is accurate.
        self.error_counter = error_counter

        self.backups = BackupService(settings)
        self.health = HealthService(database, started_at=self.started_at)

        #: Set during startup once the Discord adapter exists.
        self.publishing: "PublishingService | None" = None

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.database.session() as session:
            yield session

    def is_owner(self, discord_user_id: int) -> bool:
        return discord_user_id in set(self.settings.bot_owner_ids)
