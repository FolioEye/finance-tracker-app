"""Redis-backed refresh-token revocation store (denylist), keyed by the
token's `jti`. See docs/adr/ADR-009-login-session-management.md for why
this is scoped to the refresh token only -- the access token is short-lived
enough (15 min) to be left to expire naturally rather than checked against
this store on every request.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod

from redis.asyncio import Redis

_KEY_PREFIX = "revoked_jti:"


class TokenRevocationStore(ABC):
    @abstractmethod
    async def revoke(self, jti: str, expires_at_epoch: int) -> None:
        """Marks `jti` as revoked until the token's own natural expiry --
        no need to keep a denylist entry any longer than the token itself
        would have been valid for."""
        ...

    @abstractmethod
    async def is_revoked(self, jti: str) -> bool:
        ...


class RedisTokenRevocationStore(TokenRevocationStore):
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def revoke(self, jti: str, expires_at_epoch: int) -> None:
        ttl_seconds = max(int(expires_at_epoch - time.time()), 1)
        await self._redis.set(f"{_KEY_PREFIX}{jti}", "1", ex=ttl_seconds)

    async def is_revoked(self, jti: str) -> bool:
        return bool(await self._redis.exists(f"{_KEY_PREFIX}{jti}"))
