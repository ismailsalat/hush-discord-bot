"""In-memory sliding-window rate limiting and duplicate-interaction guards.

Deliberately in-process: these limits protect a single bot instance from button
spam and accidental double submits. Durable, cross-instance limits belong in the
database constraints (unique keys on ratings, follows, reports and confessions).
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field


@dataclass(slots=True)
class RateLimitRule:
    limit: int
    window_seconds: int
    description: str = "that"


@dataclass(slots=True)
class RateLimiter:
    """Sliding-window counter keyed by an arbitrary string."""

    _events: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))

    def check(self, key: str, rule: RateLimitRule, *, now: float | None = None) -> int:
        """Return ``0`` when allowed, otherwise seconds until the next slot.

        This does not consume a slot; call :meth:`hit` to record usage.
        """
        now = time.monotonic() if now is None else now
        bucket = self._events[key]
        self._evict(bucket, now, rule.window_seconds)
        if len(bucket) < rule.limit:
            return 0
        return max(1, int(bucket[0] + rule.window_seconds - now))

    def hit(self, key: str, rule: RateLimitRule, *, now: float | None = None) -> int:
        """Consume a slot if available. Returns retry-after seconds if blocked."""
        now = time.monotonic() if now is None else now
        retry_after = self.check(key, rule, now=now)
        if retry_after:
            return retry_after
        self._events[key].append(now)
        return 0

    def reset(self, key: str) -> None:
        self._events.pop(key, None)

    def clear(self) -> None:
        self._events.clear()

    @staticmethod
    def _evict(bucket: deque[float], now: float, window: int) -> None:
        cutoff = now - window
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()


@dataclass(slots=True)
class InteractionGuard:
    """Rejects a repeated Discord interaction id (double click / client retry).

    Interaction ids are unique per user action, so seeing one twice means the
    same click arrived twice.
    """

    ttl_seconds: int = 900
    _seen: dict[str, float] = field(default_factory=dict)

    def is_duplicate(self, interaction_id: str | int) -> bool:
        now = time.monotonic()
        self._prune(now)
        key = str(interaction_id)
        if key in self._seen:
            return True
        self._seen[key] = now
        return False

    def _prune(self, now: float) -> None:
        if len(self._seen) < 512:
            return
        cutoff = now - self.ttl_seconds
        for key in [k for k, seen in self._seen.items() if seen <= cutoff]:
            self._seen.pop(key, None)


@dataclass(slots=True)
class InFlightGuard:
    """Prevents a second concurrent run of the same logical operation.

    Used so a user hammering ``Post`` cannot start two creation flows before the
    first one has written its row.
    """

    _active: set[str] = field(default_factory=set)

    def acquire(self, key: str) -> bool:
        if key in self._active:
            return False
        self._active.add(key)
        return True

    def release(self, key: str) -> None:
        self._active.discard(key)
