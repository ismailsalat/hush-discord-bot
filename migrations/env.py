"""Alembic environment.

Reads the database URL from application settings so migrations and the running
bot can never disagree about which database they are pointed at.
"""

from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.settings import get_settings  # noqa: E402
from app.database.base import Base  # noqa: E402
import app.database.models  # noqa: E402,F401  (registers every table on Base)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# When Alembic is driven programmatically (app.database.migrations) the caller
# supplies the URL through config.attributes. From the CLI there is no caller,
# so fall back to application settings. Without this the two paths can disagree
# about which database they are migrating.
_database_url = config.attributes.get("database_url") or get_settings().database_url
config.set_main_option("sqlalchemy.url", _database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        # Batch mode lets SQLite handle ALTER TABLE, so the same migrations
        # work on both SQLite and PostgreSQL.
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
