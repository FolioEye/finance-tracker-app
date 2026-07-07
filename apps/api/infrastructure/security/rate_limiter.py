"""Redis-backed fixed-window rate limiter. Port + adapter, per hexagonal
architecture -- see docs/adr/ADR-009-login-session-management.md for why
this exists alongside (not instead of) the slowapi limiter already used by
/register.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from redis.asyncio import Redis


class RateLimitExceededError(Exception):
    """Raised by callers (application layer) when a rate limit check should
    short-circuit before any further work -- in particular, before any
    database access."""


class RateLimiter(ABC):
    @abstractmethod
    async def check_and_increment(self, key: str, max_attempts: int, window_seconds: int) -> bool:
        """Returns True if this attempt is allowed, False if `key` has
        already hit `max_attempts` within the current `window_seconds`
        window. Increments the counter as part of the same call."""
        ...


class RedisRateLimiter(RateLimiter):
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def check_and_increment(self, key: str, max_attempts: int, window_seconds: int) -> bool:
        # Fixed-window counter: INCR then, only on the very first hit in a
        # window, set the expiry. There's a small window between the INCR
        # and the EXPIRE where a process crash could leave a key with no
        # expiry -- an accepted trade-off for a login rate limiter (worst
        # case is a stuck counter that never resets, not a bypass); see
        # ADR-009 for the full comparison against alternatives.
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, window_seconds)
        return count <= max_attempts
