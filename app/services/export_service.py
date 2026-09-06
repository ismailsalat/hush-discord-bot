"""Permission-scoped data exports.

Two rules govern everything here:

* the requester's permission level decides *which rows* they can pull
* the requester's permission level decides *whether identity columns survive*

Only the bot owner ever sees ``discord_user_id``. Guild admins can export their
own guild's data, but it comes back with the Discord mapping stripped, so an
export can never become a de-anonymisation tool.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.core.constants import ExportFormat, ExportScope, LedgerAction, PermissionLevel
from app.core.exceptions import ExportError, ExportPermissionError
from app.database.models import (
    Agreement,
    AnonAlias,
    Ban,
    Bookmark,
    Confession,
    Follow,
    Guild,
    GuildSettings,
    ModerationLedger,
    ModerationWarning,
    Notification,
    Poll,
    PollOption,
    PollVote,
    Rating,
    Report,
    User,
)
from app.database.repositories import (
    AliasRepository,
    ExportRepository,
    ModerationRepository,
    UserRepository,
)
from app.exports import write_csv, write_json, write_txt, write_zip
from app.exports.bundle import ExportBundle
from app.exports.txt_exporter import dumps as txt_dumps
from app.logging.audit import log_export
from app.security.identifiers import normalize_alias
from app.utils.time import utcnow

#: Columns removed unless the requester is the bot owner.
IDENTITY_COLUMNS = {"discord_user_id", "requested_by_discord_id"}


@dataclass(frozen=True, slots=True)
class ExportResult:
    export_id: str
    path: Path
    filename: str
    size_bytes: int
    row_counts: dict[str, int]
    redacted: bool


class ExportService:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)
        self.aliases = AliasRepository(session)
        self.exports = ExportRepository(session)
        self.ledger = ModerationRepository(session)

    # --- Permission model --------------------------------------------------

    @staticmethod
    def required_level(scope: ExportScope) -> PermissionLevel:
        if scope in {ExportScope.FULL}:
            return PermissionLevel.BOT_OWNER
        return PermissionLevel.ADMIN

    def _check(self, scope: ExportScope, level: PermissionLevel) -> bool:
        """Returns whether identity columns should be redacted."""
        required = self.required_level(scope)
        if not level.meets(required):
            raise ExportPermissionError(
                f"{level} cannot export {scope}",
                user_message=f"Exporting {scope.value.lower().replace('_', ' ')} data "
                f"requires the {required.value.lower()} permission level.",
            )
        return not level.meets(PermissionLevel.BOT_OWNER)

    def _rows(self, instances: list[Any], *, redact: bool) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for instance in instances:
            row = instance.to_dict()
            if redact:
                for column in IDENTITY_COLUMNS:
                    row.pop(column, None)
            rows.append(row)
        return rows

    # --- Target resolution -------------------------------------------------

    async def resolve_internal_user_id(
        self, *, discord_user_id: int | None = None, internal_user_id: str | None = None,
        public_alias: str | None = None, guild_id: int | None = None,
    ) -> str | None:
        """Accept any of the four supported identifiers for a person."""
        if internal_user_id:
            user = await self.users.get(internal_user_id)
            return user.id if user else None
        if discord_user_id:
            user = await self.users.get_by_discord_id(discord_user_id)
            return user.id if user else None
        if public_alias and guild_id:
            normalized = normalize_alias(public_alias)
            if normalized is None:
                return None
            alias = await self.aliases.get_by_public_alias(guild_id, normalized)
            return alias.internal_user_id if alias else None
        return None

    # --- Bundle builders ---------------------------------------------------

    async def _fetch(self, model, *conditions) -> list[Any]:
        query = select(model)
        for condition in conditions:
            query = query.where(condition)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def build_user_bundle(
        self, internal_user_id: str, *, redact: bool, guild_id: int | None = None
    ) -> ExportBundle:
        bundle = ExportBundle(scope=ExportScope.USER.value, target=internal_user_id,
                              guild_id=guild_id)

        confessions = await self._fetch(Confession, Confession.internal_user_id == internal_user_id)
        confession_ids = [item.id for item in confessions]

        bundle.add("profile", self._rows(
            await self._fetch(User, User.id == internal_user_id), redact=redact))
        bundle.add("aliases", self._rows(
            await self._fetch(AnonAlias, AnonAlias.internal_user_id == internal_user_id),
            redact=redact))
        bundle.add("agreements", self._rows(
            await self._fetch(Agreement, Agreement.internal_user_id == internal_user_id),
            redact=redact))
        bundle.add("confessions", self._rows(confessions, redact=redact))
        bundle.add("ratings", self._rows(
            await self._fetch(Rating, Rating.voter_internal_user_id == internal_user_id),
            redact=redact))
        bundle.add("follows", self._rows(
            await self._fetch(Follow, Follow.follower_internal_user_id == internal_user_id),
            redact=redact))
        bundle.add("bookmarks", self._rows(
            await self._fetch(Bookmark, Bookmark.internal_user_id == internal_user_id),
            redact=redact))
        bundle.add("warnings", self._rows(
            await self._fetch(
                ModerationWarning, ModerationWarning.internal_user_id == internal_user_id),
            redact=redact))
        bundle.add("bans", self._rows(
            await self._fetch(Ban, Ban.internal_user_id == internal_user_id), redact=redact))
        bundle.add("reports", self._rows(
            await self._fetch(Report, Report.confession_id.in_(confession_ids))
            if confession_ids else [], redact=redact))
        bundle.add("notifications", self._rows(
            await self._fetch(Notification, Notification.internal_user_id == internal_user_id),
            redact=redact))
        bundle.add("moderation", self._rows(
            await self._fetch(
                ModerationLedger, ModerationLedger.internal_user_id == internal_user_id),
            redact=redact))
        return bundle

    async def build_alias_bundle(self, alias_id: str, *, redact: bool) -> ExportBundle:
        """Only what is publicly attributable to this alias - not the account."""
        alias = await self.aliases.get(alias_id)
        if alias is None:
            raise ExportError("alias not found", user_message="That alias was not found.")

        bundle = ExportBundle(scope=ExportScope.ALIAS.value, target=alias.public_alias,
                              guild_id=alias.guild_id)
        confessions = await self._fetch(Confession, Confession.alias_id == alias_id)
        confession_ids = [item.id for item in confessions]

        bundle.add("alias", self._rows([alias], redact=redact))
        bundle.add("confessions", self._rows(confessions, redact=redact))
        bundle.add("ratings", self._rows(
            await self._fetch(Rating, Rating.confession_id.in_(confession_ids))
            if confession_ids else [], redact=redact))
        bundle.add("follows", self._rows(
            await self._fetch(Follow, Follow.alias_id == alias_id), redact=redact))
        return bundle

    async def build_confession_bundle(self, confession_id: str, *, redact: bool) -> ExportBundle:
        confession = await self.session.get(Confession, confession_id)
        if confession is None:
            raise ExportError("not found", user_message="That confession was not found.")

        bundle = ExportBundle(scope=ExportScope.CONFESSION.value, target=confession_id,
                              guild_id=confession.guild_id)
        bundle.add("confession", self._rows([confession], redact=redact))
        bundle.add("ratings", self._rows(
            await self._fetch(Rating, Rating.confession_id == confession_id), redact=redact))
        bundle.add("bookmarks", self._rows(
            await self._fetch(Bookmark, Bookmark.confession_id == confession_id), redact=redact))
        bundle.add("reports", self._rows(
            await self._fetch(Report, Report.confession_id == confession_id), redact=redact))

        polls = await self._fetch(Poll, Poll.confession_id == confession_id)
        poll_ids = [poll.id for poll in polls]
        bundle.add("polls", self._rows(polls, redact=redact))
        bundle.add("poll_votes", self._rows(
            await self._fetch(PollVote, PollVote.poll_id.in_(poll_ids)) if poll_ids else [],
            redact=redact))
        return bundle

    async def build_guild_bundle(
        self, guild_id: int, *, redact: bool, scope: ExportScope = ExportScope.GUILD
    ) -> ExportBundle:
        bundle = ExportBundle(scope=scope.value, target=str(guild_id), guild_id=guild_id)

        confessions = await self._fetch(Confession, Confession.guild_id == guild_id)
        confession_ids = [item.id for item in confessions]

        if scope in {ExportScope.GUILD, ExportScope.CONFESSIONS_ONLY}:
            bundle.add("confessions", self._rows(confessions, redact=redact))

        if scope in {ExportScope.GUILD, ExportScope.REPORTS_ONLY}:
            bundle.add("reports", self._rows(
                await self._fetch(Report, Report.guild_id == guild_id), redact=redact))

        if scope in {ExportScope.GUILD, ExportScope.MODERATION}:
            bundle.add("warnings", self._rows(
                await self._fetch(ModerationWarning, ModerationWarning.guild_id == guild_id),
                redact=redact))
            bundle.add("bans", self._rows(
                await self._fetch(Ban, Ban.guild_id == guild_id), redact=redact))
            bundle.add("moderation_ledger", self._rows(
                await self._fetch(ModerationLedger, ModerationLedger.guild_id == guild_id),
                redact=redact))

        if scope is ExportScope.GUILD:
            bundle.add("guild", self._rows(
                await self._fetch(Guild, Guild.id == guild_id), redact=redact))
            bundle.add("settings", self._rows(
                await self._fetch(GuildSettings, GuildSettings.guild_id == guild_id),
                redact=redact))
            bundle.add("aliases", self._rows(
                await self._fetch(AnonAlias, AnonAlias.guild_id == guild_id), redact=redact))
            bundle.add("ratings", self._rows(
                await self._fetch(Rating, Rating.confession_id.in_(confession_ids))
                if confession_ids else [], redact=redact))
            bundle.add("follows", self._rows(
                await self._fetch(Follow, Follow.guild_id == guild_id), redact=redact))
        return bundle

    async def build_full_bundle(self, *, redact: bool) -> ExportBundle:
        bundle = ExportBundle(scope=ExportScope.FULL.value)
        models = {
            "users": User, "guilds": Guild, "settings": GuildSettings, "agreements": Agreement,
            "aliases": AnonAlias, "confessions": Confession, "ratings": Rating,
            "follows": Follow, "bookmarks": Bookmark, "polls": Poll,
            "poll_options": PollOption, "poll_votes": PollVote, "reports": Report,
            "warnings": ModerationWarning, "bans": Ban,
            "moderation_ledger": ModerationLedger, "notifications": Notification,
        }
        for name, model in models.items():
            bundle.add(name, self._rows(await self._fetch(model), redact=redact))
        return bundle

    # --- Public entry point ------------------------------------------------

    async def export(
        self,
        *,
        scope: ExportScope,
        actor_level: PermissionLevel,
        actor_id: int,
        export_format: ExportFormat = ExportFormat.ZIP,
        guild_id: int | None = None,
        internal_user_id: str | None = None,
        alias_id: str | None = None,
        confession_id: str | None = None,
    ) -> ExportResult:
        """Build, write and record an export. Always audited."""
        redact = self._check(scope, actor_level)

        if scope is ExportScope.USER:
            if not internal_user_id:
                raise ExportError("no target", user_message="Specify who to export.")
            bundle = await self.build_user_bundle(
                internal_user_id, redact=redact, guild_id=guild_id
            )
            target = internal_user_id
        elif scope is ExportScope.ALIAS:
            if not alias_id:
                raise ExportError("no target", user_message="Specify an alias to export.")
            bundle = await self.build_alias_bundle(alias_id, redact=redact)
            target = alias_id
        elif scope is ExportScope.CONFESSION:
            if not confession_id:
                raise ExportError("no target", user_message="Specify a confession to export.")
            bundle = await self.build_confession_bundle(confession_id, redact=redact)
            target = confession_id
        elif scope is ExportScope.FULL:
            bundle = await self.build_full_bundle(redact=redact)
            target = "full"
        else:
            if not guild_id:
                raise ExportError("no guild", user_message="Specify a server to export.")
            bundle = await self.build_guild_bundle(guild_id, redact=redact, scope=scope)
            target = str(guild_id)

        bundle.finalize(requested_by=actor_id, redacted=redact)

        directory = Path(self.settings.export_directory)
        stamp = utcnow().strftime("%Y%m%d-%H%M%S")
        base = f"{scope.value.lower()}_{_safe(target)}_{stamp}"

        if export_format is ExportFormat.ZIP:
            filename = f"{base}.zip"
            path = write_zip(directory / filename, bundle)
        elif export_format is ExportFormat.JSON:
            filename = f"{base}.json"
            path = write_json(
                directory / filename, {"metadata": bundle.metadata, "tables": bundle.tables}
            )
        elif export_format is ExportFormat.TXT:
            filename = f"{base}.txt"
            path = write_txt(directory / filename, txt_dumps(bundle.metadata, bundle.tables))
        else:
            filename = f"{base}.csv"
            largest = max(bundle.tables.items(), key=lambda item: len(item[1]), default=("", []))
            path = write_csv(directory / filename, largest[1])

        size = path.stat().st_size
        record = await self.exports.create(
            requested_by_discord_id=actor_id,
            scope=scope,
            export_format=export_format,
            guild_id=guild_id,
            target=target,
            file_path=str(path),
            size_bytes=size,
            row_counts=bundle.row_counts(),
            retention_hours=self.settings.export_retention_hours,
        )
        await self.ledger.record(
            LedgerAction.EXPORT_CREATED,
            guild_id=guild_id,
            moderator_id=actor_id,
            internal_user_id=internal_user_id,
            reason=f"{scope.value} export",
            meta={
                "export_id": record.id,
                "format": export_format.value,
                "redacted": redact,
                "row_counts": bundle.row_counts(),
            },
        )
        log_export(actor_id=actor_id, scope=scope.value, target=target, guild_id=guild_id)

        return ExportResult(
            export_id=record.id,
            path=path,
            filename=filename,
            size_bytes=size,
            row_counts=bundle.row_counts(),
            redacted=redact,
        )

    async def cleanup_expired(self) -> int:
        """Delete generated export files past their retention window."""
        removed = 0
        for record in await self.exports.list_expired():
            if record.file_path:
                file_path = Path(record.file_path)
                if file_path.exists():
                    file_path.unlink(missing_ok=True)
            await self.exports.mark_deleted(record.id)
            removed += 1
        return removed


def _safe(value: str | None) -> str:
    if not value:
        return "unknown"
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in value)[:40]
