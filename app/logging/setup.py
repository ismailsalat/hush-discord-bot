"""Structured logging configuration.

Four logical streams are kept separate so they can be routed and retained
independently:

``hush.app``        application events, failures, background jobs
``hush.security``   permission denials, identity lookups, exports
``hush.moderation`` moderation events mirrored from the database ledger
``hush.metrics``    counters and timings for the health command
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Any

import structlog

from app.security.privacy import scrub

APP_LOGGER = "hush.app"
SECURITY_LOGGER = "hush.security"
MODERATION_LOGGER = "hush.moderation"
METRICS_LOGGER = "hush.metrics"

_STREAMS = {
    APP_LOGGER: "application.log",
    SECURITY_LOGGER: "security.log",
    MODERATION_LOGGER: "moderation.log",
    METRICS_LOGGER: "metrics.log",
}

_configured = False


def _scrub_processor(_logger: Any, _name: str, event_dict: dict) -> dict:
    """Drop secrets before anything reaches a handler."""
    return scrub(event_dict)


def configure_logging(
    *,
    level: str = "INFO",
    json_output: bool = False,
    log_directory: Path | None = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """Configure structlog + stdlib logging. Safe to call more than once."""
    global _configured

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        timestamper,
        _scrub_processor,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    renderer = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    root.addHandler(stdout_handler)
    root.setLevel(level)

    if log_directory is not None:
        log_directory.mkdir(parents=True, exist_ok=True)
        for logger_name, filename in _STREAMS.items():
            stream_logger = logging.getLogger(logger_name)
            for handler in list(stream_logger.handlers):
                stream_logger.removeHandler(handler)
            file_handler = logging.handlers.RotatingFileHandler(
                log_directory / filename,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            stream_logger.addHandler(file_handler)
            stream_logger.setLevel(level)

    # discord.py is chatty at INFO; keep its gateway noise at WARNING.
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str = APP_LOGGER) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger for one of the four streams."""
    if not _configured:
        configure_logging()
    return structlog.get_logger(name)


def app_logger() -> structlog.stdlib.BoundLogger:
    return get_logger(APP_LOGGER)


def security_logger() -> structlog.stdlib.BoundLogger:
    return get_logger(SECURITY_LOGGER)


def moderation_logger() -> structlog.stdlib.BoundLogger:
    return get_logger(MODERATION_LOGGER)


def metrics_logger() -> structlog.stdlib.BoundLogger:
    return get_logger(METRICS_LOGGER)


def configure_from_settings(settings) -> None:
    """Configure logging from a :class:`Settings` object.

    A thin wrapper so callers do not have to unpack five keyword arguments, and
    so the settings-to-logging mapping lives in exactly one place.
    """
    configure_logging(
        level=settings.log_level,
        json_output=settings.log_json,
        log_directory=Path(settings.log_directory),
    )
