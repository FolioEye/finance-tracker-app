"""Shared async Redis client -- one connection pool per process, mirroring
session.py's SQLAlchemy engine pattern (constraint matrix: connection
pooling, not a fresh connection per call).
"""
from __future__ import annotations

from redis.asyncio import Redis, from_url

from apps.api.config import get_settings

_settings = get_settings()

redis_client: Redis = from_url(_settings.redis_url, decode_responses=True, max_connections=10)
