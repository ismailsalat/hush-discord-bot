"""Short error references that connect a user's screenshot to a stack trace."""

from __future__ import annotations

from collections import deque
from datetime import timedelta

import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.logging.setup import app_logger
from app.security.identifiers import new_error_id
from app.utils.time import utcnow


@dataclass(slots=True)
class ErrorReport:
    """A logged unexpected error, identified by a user-visible short code."""

    error_id: str
    timestamp: datetime
    operation: str
    exception_type: str
    message: str
    guild_id: int | None = None
    user_reference: str | None = None
    interaction: str | None = None
    context: dict[str, Any] = field(default_factory=dict)


class ErrorCounter:
    """Rolling count of unexpected errors, for `/admin status`.

    Deliberately in-memory and approximate: it answers "is something wrong right
    now?" without adding a write to the hot path of a failure.
    """

    def __init__(self, window_seconds: int = 3600, cap: int = 5000):
        self.window_seconds = window_seconds
        self.cap = cap
        self._timestamps: deque[datetime] = deque(maxlen=cap)

    def record(self) -> None:
        self._timestamps.append(utcnow())

    def count_last_hour(self) -> int:
        cutoff = utcnow() - timedelta(seconds=self.window_seconds)
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()
        return len(self._timestamps)

    def reset(self) -> None:
        self._timestamps.clear()


#: Process-wide counter. Incremented by every ``report_exception`` call.
error_counter = ErrorCounter()


def report_exception(
    exc: BaseException,
    *,
    operation: str,
    guild_id: int | None = None,
    user_reference: str | None = None,
    interaction: str | None = None,
    **context: Any,
) -> ErrorReport:
    """Log an unexpected exception with a fresh error id and return the report.

    ``user_reference`` should be an internal id or alias - never a Discord tag,
    so logs do not become an identity index.
    """
    report = ErrorReport(
        error_id=new_error_id(),
        timestamp=utcnow(),
        operation=operation,
        exception_type=type(exc).__name__,
        message=str(exc),
        guild_id=guild_id,
        user_reference=user_reference,
        interaction=interaction,
        context=context,
    )
    error_counter.record()
    app_logger().error(
        "unhandled_error",
        error_id=report.error_id,
        operation=operation,
        exception_type=report.exception_type,
        error_message=report.message,
        guild_id=guild_id,
        user_reference=user_reference,
        interaction=interaction,
        stack="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        **context,
    )
    return report
