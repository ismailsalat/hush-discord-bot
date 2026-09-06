"""Entry point.

``python -m app.main``
"""

from __future__ import annotations

import asyncio
import signal
import sys

from app.bot import HushBot
from app.config.settings import get_settings
from app.database.session import Database
from app.logging.setup import app_logger, configure_from_settings


async def run() -> int:
    settings = get_settings()
    settings.ensure_directories()
    configure_from_settings(settings)
    log = app_logger()

    # Fail clearly and completely rather than starting a half-broken bot.
    problems = settings.validate_for_startup()
    if problems:
        log.error("invalid_configuration", problems=problems)
        print("\nHush cannot start. Fix the following:\n", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print("\nSee .env.example for the full list of settings.\n", file=sys.stderr)
        return 2

    log.info("BOT_START", version=settings.version, **settings.safe_dump())

    database = Database.from_settings(settings)
    if not await database.healthcheck():
        log.error(
            "database_unreachable",
            hint="Check DATABASE_URL and that migrations have been applied.",
        )
        return 3

    bot = HushBot(settings, database)

    loop = asyncio.get_running_loop()
    for signal_name in ("SIGTERM", "SIGINT"):
        try:
            loop.add_signal_handler(
                getattr(signal, signal_name), lambda: asyncio.create_task(bot.close())
            )
        except (NotImplementedError, AttributeError):  # pragma: no cover - Windows
            pass

    try:
        await bot.start(settings.discord_token)
    except Exception as exc:
        log.error("fatal", error=str(exc), error_type=type(exc).__name__)
        return 1
    finally:
        if not bot.is_closed():
            await bot.close()
        await database.dispose()
    return 0


def main() -> None:
    try:
        sys.exit(asyncio.run(run()))
    except KeyboardInterrupt:  # pragma: no cover
        sys.exit(0)


if __name__ == "__main__":
    main()
