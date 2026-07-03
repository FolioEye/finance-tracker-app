"""Async SQLAlchemy engine + session factory. Pooled per constraint matrix (min 2, max 10)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.api.config import get_settings

_settings = get_settings()

engine = create_async_engine(
    _settings.database_url,
    pool_size=_settings.db_pool_min_size,
    max_overflow=_settings.db_pool_max_size - _settings.db_pool_min_size,
    pool_timeout=_settings.db_query_timeout_seconds,
    pool_pre_ping=True,
)

_SessionFactory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    async with _SessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
