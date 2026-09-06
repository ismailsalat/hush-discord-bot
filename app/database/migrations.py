"""Programmatic Alembic access.

Railway runs one process, so the bot checks and (by default) applies migrations
itself at startup. That removes a whole class of "deployed but the schema is
old" failures without needing a separate release step.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import AsyncEngine

from app.logging.setup import app_logger

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


def build_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    # env.py reads this first, so the programmatic path and the CLI path can
    # never end up pointed at different databases.
    config.attributes["database_url"] = database_url
    return config


def head_revision(database_url: str) -> str | None:
    script = ScriptDirectory.from_config(build_config(database_url))
    return script.get_current_head()


async def current_revision(engine: AsyncEngine) -> str | None:
    """The revision the database is actually on."""

    def _read(connection) -> str | None:
        return MigrationContext.configure(connection).get_current_revision()

    async with engine.connect() as connection:
        return await connection.run_sync(_read)


async def upgrade_to_head(database_url: str) -> None:
    """Run ``alembic upgrade head``.

    Alembic is synchronous, so it runs in a worker thread to keep the event
    loop free.
    """
    await asyncio.to_thread(command.upgrade, build_config(database_url), "head")


async def ensure_schema(engine: AsyncEngine, database_url: str, *, auto_apply: bool) -> str:
    """Make sure the database schema matches the code.

    Returns a short human-readable description of what happened. Raises if the
    schema is behind and ``auto_apply`` is off, because running a bot against an
    old schema fails in confusing ways later rather than clearly now.
    """
    head = head_revision(database_url)
    current = await current_revision(engine)

    if current == head:
        return f"up to date ({head})"

    if not auto_apply:
        raise RuntimeError(
            f"database is at revision {current or 'none'} but the code expects {head}. "
            "Run 'alembic upgrade head', or set RUN_MIGRATIONS_ON_START=true."
        )

    app_logger().warning(
        "migrations_applying", current=current or "none", target=head
    )
    await upgrade_to_head(database_url)
    return f"upgraded {current or 'empty'} -> {head}"
