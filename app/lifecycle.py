"""Startup and shutdown sequencing.

Startup runs a fixed checklist and logs each step, so if the bot is unhealthy
the log says exactly which stage was reached. Anything non-fatal degrades with
a warning rather than preventing the bot from coming up at all.
"""

from __future__ import annotations

from discord.ext import commands

from app.cogs import EXTENSIONS
from app.core.runtime import Runtime
from app.logging.setup import app_logger
from app.publisher import DiscordPublisher
from app.services.publishing_service import PublishingService
from app.tasks.maintenance import MaintenanceTasks
from app.tasks.notifications import NotificationDispatcher
from app.tasks.scheduler import TaskScheduler

HOUR = 3600
MINUTE = 60


async def load_extensions(bot: commands.Bot) -> list[str]:
    loaded: list[str] = []
    for extension in EXTENSIONS:
        try:
            await bot.load_extension(extension)
            loaded.append(extension)
        except Exception as exc:
            app_logger().error("extension_failed", extension=extension, error=str(exc))
            raise
    return loaded


def register_persistent_views(bot: commands.Bot) -> None:
    """Re-arm every component that can appear on an old message.

    Dynamic items carry their subject in the custom id, so registering the
    classes is enough - no per-message state has to be reloaded.
    """
    from app.views.agreement import AgreeButton, CancelAgreementButton
    from app.views.confession import PERSISTENT_ITEMS as CONFESSION_ITEMS
    from app.views.home import HomeView
    from app.views.notices import ContinueView, NoticeAcknowledgeButton
    from app.views.polls import PERSISTENT_ITEMS as POLL_ITEMS

    for item in (
        *CONFESSION_ITEMS,
        *POLL_ITEMS,
        AgreeButton,
        CancelAgreementButton,
        NoticeAcknowledgeButton,
    ):
        bot.add_dynamic_items(item)

    # Static custom ids still need their view registered once.
    bot.add_view(HomeView())
    bot.add_view(ContinueView())


def build_scheduler(runtime: Runtime, bot: commands.Bot) -> TaskScheduler:
    scheduler = TaskScheduler()
    maintenance = MaintenanceTasks(runtime, client=bot)
    dispatcher = NotificationDispatcher(bot, runtime)

    scheduler.register("notifications", 60, dispatcher.deliver_pending, initial_delay=15)
    scheduler.register("ban_expiry", 5 * MINUTE, maintenance.expire_bans, initial_delay=30)
    scheduler.register("reconciliation", 10 * MINUTE, maintenance.reconcile, initial_delay=20)
    scheduler.register("cleanup", HOUR, maintenance.cleanup, initial_delay=120)
    scheduler.register("metrics", 15 * MINUTE, maintenance.metrics, initial_delay=60)

    if runtime.settings.backup_enabled:
        scheduler.register("backup_hourly", HOUR, maintenance.hourly_backup, initial_delay=300)
        scheduler.register(
            "backup_daily", 24 * HOUR, maintenance.daily_backup, initial_delay=600
        )
        scheduler.register(
            "backup_weekly", 7 * 24 * HOUR, maintenance.weekly_backup, initial_delay=900
        )
    return scheduler


async def startup_sequence(bot: commands.Bot) -> None:
    """The ordered checklist run once the gateway connection is ready."""
    runtime: Runtime = bot.runtime  # type: ignore[attr-defined]
    log = app_logger()
    step = 0

    def mark(name: str, **fields) -> None:
        nonlocal step
        step += 1
        log.info("startup_step", step=step, stage=name, **fields)

    # 1. Database reachable.
    healthy = await runtime.database.healthcheck()
    mark("database", ok=healthy)
    if not healthy:
        raise RuntimeError("database healthcheck failed at startup")

    # 2. Schema matches the code. Refuses to run against an old schema.
    from app.database.migrations import ensure_schema

    schema = await ensure_schema(
        runtime.database.engine,
        runtime.settings.database_url,
        auto_apply=runtime.settings.run_migrations_on_start,
    )
    mark("migrations", detail=schema)

    # 2. Guild records exist for everywhere we are.
    async with runtime.session() as session:
        from app.database.repositories import GuildRepository

        guilds = GuildRepository(session)
        for guild in bot.guilds:
            await guilds.get_or_create_settings(guild.id, runtime.settings, name=guild.name)
    mark("guild_records", guilds=len(bot.guilds))

    # 3. Publishing adapter.
    runtime.publishing = PublishingService(
        runtime.database, runtime.settings, DiscordPublisher(bot, runtime)
    )
    mark("publisher")

    # 4. Persistent components re-armed.
    register_persistent_views(bot)
    mark("persistent_views")

    # 5. Repair anything left mid-flight by the previous process.
    maintenance = MaintenanceTasks(runtime, client=bot)
    reconciled = await maintenance.reconcile()
    mark("reconciliation", detail=reconciled or "nothing to repair")

    # 6. Expire bans that lapsed while offline.
    expired = await maintenance.expire_bans()
    mark("ban_expiry", detail=expired or "none due")

    # 7. Clear out stale drafts and exports.
    cleaned = await maintenance.cleanup()
    mark("cleanup", detail=cleaned or "nothing to clean")

    # 8. Verify confession channels still exist and are writable.
    degraded = await verify_channels(bot, runtime)
    mark("channel_check", degraded=degraded)

    # 9. Health checks that depend on Discord.
    runtime.health.register("discord", lambda: (bot.is_ready(), f"{len(bot.guilds)} guild(s)"))
    runtime.health.register("backups", runtime.backups.status)
    mark("health_checks")

    # 10. Background tasks.
    scheduler = build_scheduler(runtime, bot)
    bot.scheduler = scheduler  # type: ignore[attr-defined]
    await scheduler.start()
    mark("scheduler", tasks=len(scheduler.tasks))

    # 11. Sync slash commands.
    synced = await bot.tree.sync()
    mark("command_sync", commands=len(synced))

    # 12. Ready.
    mark("ready", user=str(bot.user), brand=runtime.settings.brand_name)


async def verify_channels(bot: commands.Bot, runtime: Runtime) -> int:
    """Warn about servers whose confession channel is gone or unwritable."""
    degraded = 0
    async with runtime.session() as session:
        from app.database.repositories import GuildRepository

        guilds = GuildRepository(session)
        for guild in bot.guilds:
            settings = await guilds.get_settings(guild.id)
            if settings is None or not settings.confession_channel_id:
                continue
            channel = guild.get_channel(settings.confession_channel_id)
            if channel is None:
                app_logger().warning("channel_missing", guild_id=guild.id)
                degraded += 1
                continue
            permissions = channel.permissions_for(guild.me)
            if not (permissions.send_messages and permissions.embed_links):
                app_logger().warning("channel_permissions_missing", guild_id=guild.id)
                degraded += 1
    return degraded


async def shutdown_sequence(bot: commands.Bot) -> None:
    runtime: Runtime = bot.runtime  # type: ignore[attr-defined]
    scheduler = getattr(bot, "scheduler", None)
    if scheduler is not None:
        await scheduler.stop()
    await runtime.database.dispose()
    app_logger().info("shutdown_complete")
