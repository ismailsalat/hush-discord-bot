"""Startup, shutdown and migration behaviour."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.core.runtime import Runtime
from app.database.migrations import current_revision, ensure_schema, head_revision
from app.database.session import Database
from app.tasks.scheduler import TaskScheduler


@pytest.fixture
def file_settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'lifecycle.sqlite3'}",
        discord_token="x",
        bot_owner_ids=[1],
        backup_directory=tmp_path / "b",
        export_directory=tmp_path / "e",
        log_directory=tmp_path / "l",
    )


class TestMigrations:
    async def test_fresh_database_is_upgraded_to_head(self, file_settings):
        database = Database(file_settings.database_url)
        try:
            assert await current_revision(database.engine) is None
            detail = await ensure_schema(
                database.engine, file_settings.database_url, auto_apply=True
            )
            assert "upgraded" in detail
            assert await current_revision(database.engine) == head_revision(
                file_settings.database_url
            )
        finally:
            await database.dispose()

    async def test_second_run_is_a_no_op(self, file_settings):
        database = Database(file_settings.database_url)
        try:
            await ensure_schema(database.engine, file_settings.database_url, auto_apply=True)
            detail = await ensure_schema(
                database.engine, file_settings.database_url, auto_apply=True
            )
            assert "up to date" in detail
        finally:
            await database.dispose()

    async def test_refuses_to_run_against_an_old_schema(self, file_settings):
        """Better a clear failure now than confusing errors later."""
        database = Database(file_settings.database_url)
        try:
            with pytest.raises(RuntimeError, match="alembic upgrade head"):
                await ensure_schema(
                    database.engine, file_settings.database_url, auto_apply=False
                )
        finally:
            await database.dispose()

    async def test_programmatic_and_cli_paths_share_a_database(self, file_settings):
        """Regression: env.py once ignored the URL it was handed."""
        database = Database(file_settings.database_url)
        try:
            await ensure_schema(database.engine, file_settings.database_url, auto_apply=True)
        finally:
            await database.dispose()
        assert Path(file_settings.database_url.split("///")[-1]).exists()


class TestScheduler:
    async def test_tasks_run_on_their_interval(self):
        runs = {"count": 0}

        async def job() -> None:
            runs["count"] += 1

        scheduler = TaskScheduler()
        scheduler.register("fast", 0.05, job, initial_delay=0.0)
        await scheduler.start()
        await asyncio.sleep(0.3)
        await scheduler.stop()
        assert runs["count"] >= 3

    async def test_stop_cancels_everything(self):
        async def job() -> None:
            await asyncio.sleep(0.01)

        scheduler = TaskScheduler()
        scheduler.register("fast", 0.05, job, initial_delay=0.0)
        await scheduler.start()
        await asyncio.sleep(0.15)
        await scheduler.stop()
        await asyncio.sleep(0.1)

        running = [
            task for task in asyncio.all_tasks() if task.get_name().startswith("hush:")
        ]
        assert running == []

    async def test_nothing_runs_after_shutdown(self):
        runs = {"count": 0}

        async def job() -> None:
            runs["count"] += 1

        scheduler = TaskScheduler()
        scheduler.register("fast", 0.05, job, initial_delay=0.0)
        await scheduler.start()
        await asyncio.sleep(0.15)
        await scheduler.stop()

        at_stop = runs["count"]
        await asyncio.sleep(0.2)
        assert runs["count"] == at_stop

    async def test_a_failing_task_does_not_kill_the_loop(self):
        """One broken job must not silently stop every other background job."""
        attempts = {"count": 0}

        async def flaky() -> None:
            attempts["count"] += 1
            raise RuntimeError("boom")

        scheduler = TaskScheduler()
        scheduler.register("flaky", 0.05, flaky, initial_delay=0.0)
        await scheduler.start()
        await asyncio.sleep(0.25)
        await scheduler.stop()

        assert attempts["count"] >= 2
        assert scheduler.tasks["flaky"].failures >= 2
        assert scheduler.tasks["flaky"].last_error

    async def test_status_is_reportable(self):
        async def job() -> None:
            return None

        scheduler = TaskScheduler()
        scheduler.register("job", 60, job, initial_delay=0.0)
        await scheduler.start()
        await asyncio.sleep(0.05)
        status = scheduler.status()
        await scheduler.stop()
        assert "job" in status


class TestShutdown:
    async def test_database_disposes_cleanly(self, file_settings):
        database = Database(file_settings.database_url)
        await database.create_all()
        assert await database.healthcheck()
        await database.dispose()

    async def test_runtime_records_a_start_time(self, file_settings):
        database = Database(file_settings.database_url)
        try:
            runtime = Runtime(file_settings, database)
            from app.utils.time import utcnow

            assert (utcnow() - runtime.started_at).total_seconds() < 5
        finally:
            await database.dispose()
