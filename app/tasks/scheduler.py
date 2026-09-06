"""Background task scheduling.

Every recurring job is registered here with an interval, so what runs and how
often is visible in one place rather than scattered across cogs. Each job is
wrapped so a failure logs and retries next tick instead of killing the loop.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from app.logging.error_ids import report_exception
from app.logging.setup import app_logger
from app.utils.time import utcnow


@dataclass
class ScheduledTask:
    name: str
    interval_seconds: float
    action: Callable[[], Awaitable[object]]
    initial_delay: float = 10.0
    last_run: object = None
    last_error: str | None = None
    runs: int = 0
    failures: int = 0
    _task: asyncio.Task | None = field(default=None, repr=False)


class TaskScheduler:
    def __init__(self) -> None:
        self.tasks: dict[str, ScheduledTask] = {}
        self._running = False

    def register(
        self,
        name: str,
        interval_seconds: float,
        action: Callable[[], Awaitable[object]],
        *,
        initial_delay: float = 10.0,
    ) -> None:
        self.tasks[name] = ScheduledTask(
            name=name,
            interval_seconds=interval_seconds,
            action=action,
            initial_delay=initial_delay,
        )

    async def start(self) -> None:
        self._running = True
        for task in self.tasks.values():
            task._task = asyncio.create_task(self._run(task), name=f"hush:{task.name}")
        app_logger().info("scheduler_started", tasks=sorted(self.tasks))

    async def stop(self) -> None:
        self._running = False
        for task in self.tasks.values():
            if task._task is not None:
                task._task.cancel()
        await asyncio.gather(
            *(task._task for task in self.tasks.values() if task._task is not None),
            return_exceptions=True,
        )
        app_logger().info("scheduler_stopped")

    async def run_once(self, name: str) -> object:
        """Run a single job immediately, for commands and tests."""
        return await self.tasks[name].action()

    async def _run(self, task: ScheduledTask) -> None:
        try:
            await asyncio.sleep(task.initial_delay)
        except asyncio.CancelledError:
            return

        while self._running:
            started = utcnow()
            try:
                result = await task.action()
                task.runs += 1
                task.last_run = started
                task.last_error = None
                if result:
                    app_logger().info("task_completed", task=task.name, result=str(result)[:200])
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                task.failures += 1
                task.last_error = str(exc)[:200]
                report_exception(exc, operation=f"task.{task.name}")

            try:
                await asyncio.sleep(task.interval_seconds)
            except asyncio.CancelledError:
                return

    def status(self) -> dict[str, str]:
        return {
            task.name: (
                f"{task.runs} runs, {task.failures} failures"
                + (f", last error: {task.last_error}" if task.last_error else "")
            )
            for task in self.tasks.values()
        }
