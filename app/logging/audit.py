"""Log-side mirror of security and moderation events.

The database ledger is the durable record; these emit the same events to the
log streams so operators can alert on them without querying Postgres.
"""

from __future__ import annotations

from typing import Any

from app.logging.setup import metrics_logger, moderation_logger, security_logger


def log_moderation(action: str, **fields: Any) -> None:
    moderation_logger().info("moderation_action", action=action, **fields)


def log_security(event_name: str, **fields: Any) -> None:
    security_logger().warning("security_event", security_event=event_name, **fields)


def log_permission_denied(*, action: str, level: str, required: str, **fields: Any) -> None:
    log_security("permission_denied", action=action, level=level, required=required, **fields)


def log_identity_lookup(*, actor_id: int, target: str, guild_id: int | None, reason: str) -> None:
    """Identity lookups are always logged, without exception."""
    log_security(
        "identity_lookup", actor_id=actor_id, target=target, guild_id=guild_id, reason=reason
    )


def log_export(*, actor_id: int, scope: str, target: str | None, guild_id: int | None) -> None:
    log_security("export_created", actor_id=actor_id, scope=scope, target=target, guild_id=guild_id)


def log_metric(name: str, value: float = 1, **fields: Any) -> None:
    metrics_logger().info("metric", metric=name, value=value, **fields)
