"""Async rate limiter with exponential backoff for Slack API / incident intake."""

from __future__ import annotations

import asyncio
import time
from collections import deque


class RateLimitError(Exception):
    """Raised when intake or Slack API must back off."""

    def __init__(self, retry_after: float, message: str = "rate limited") -> None:
        super().__init__(message)
        self.retry_after = retry_after


class AsyncRateLimiter:
    """
    Sliding-window limiter for incident intake (e.g. 30/min).

    Also tracks Slack Retry-After style backoff and exposes
    `wait_if_needed` for cooperative async callers.
    """

    def __init__(self, max_calls: int, period_seconds: float = 60.0) -> None:
        if max_calls < 1:
            raise ValueError("max_calls must be >= 1")
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()
        self._backoff_until: float = 0.0

    def _prune(self, now: float) -> None:
        cutoff = now - self.period_seconds
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

    async def acquire(self) -> None:
        """Block until a slot is available, respecting external backoff."""
        while True:
            async with self._lock:
                now = time.monotonic()
                if now < self._backoff_until:
                    wait = self._backoff_until - now
                else:
                    self._prune(now)
                    if len(self._timestamps) < self.max_calls:
                        self._timestamps.append(now)
                        return
                    wait = self.period_seconds - (now - self._timestamps[0])
            await asyncio.sleep(max(wait, 0.01))

    async def try_acquire(self) -> bool:
        """Non-blocking acquire; False if limited."""
        async with self._lock:
            now = time.monotonic()
            if now < self._backoff_until:
                return False
            self._prune(now)
            if len(self._timestamps) >= self.max_calls:
                return False
            self._timestamps.append(now)
            return True

    def note_slack_rate_limit(self, retry_after: float | None = None) -> float:
        """
        Record a Slack 429 / rate_limited response.

        Uses exponential growth capped at 60s when retry_after is omitted.
        Returns the backoff duration applied.
        """
        now = time.monotonic()
        if retry_after is not None and retry_after > 0:
            delay = float(retry_after)
        else:
            remaining = max(0.0, self._backoff_until - now)
            delay = min(60.0, max(1.0, (remaining * 2) if remaining else 1.0))
        self._backoff_until = now + delay
        return delay

    def seconds_until_available(self) -> float:
        now = time.monotonic()
        if now < self._backoff_until:
            return self._backoff_until - now
        self._prune(now)
        if len(self._timestamps) < self.max_calls:
            return 0.0
        return max(0.0, self.period_seconds - (now - self._timestamps[0]))
