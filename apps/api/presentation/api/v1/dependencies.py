"""FastAPI dependency-injection wiring.

No singletons or global mutable state -- a fresh repository/handler is
constructed per request from a pooled session, per constraint matrix.
"""
from __future__ import annotations

from typing import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.application.commands.login_user import LoginUserHandler
from apps.api.application.commands.logout_user import LogoutUserHandler
from apps.api.application.commands.register_user import RegisterUserHandler
from apps.api.config import Settings, get_settings
from apps.api.infrastructure.cache.redis_client import redis_client
from apps.api.infrastructure.database.session import get_session
from apps.api.infrastructure.repositories.sqlalchemy_user_repository import (
    SqlAlchemyUserRepository,
)
from apps.api.infrastructure.security.password_hasher import BcryptPasswordHasher
from apps.api.infrastructure.security.rate_limiter import RedisRateLimiter
from apps.api.infrastructure.security.token_revocation import RedisTokenRevocationStore
from apps.api.infrastructure.security.token_service import TokenService


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with get_session() as session:
        yield session


def get_register_user_handler(
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> RegisterUserHandler:
    repository = SqlAlchemyUserRepository(session)
    hasher = BcryptPasswordHasher(rounds=settings.bcrypt_rounds)
    tokens = TokenService(
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        access_token_expire_minutes=settings.access_token_expire_minutes,
        refresh_token_expire_days=settings.refresh_token_expire_days,
    )
    return RegisterUserHandler(
        user_repository=repository,
        password_hasher=hasher,
        token_service=tokens,
        min_password_length=settings.password_min_length,
    )


def get_login_user_handler(
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> LoginUserHandler:
    repository = SqlAlchemyUserRepository(session)
    hasher = BcryptPasswordHasher(rounds=settings.bcrypt_rounds)
    tokens = TokenService(
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        access_token_expire_minutes=settings.access_token_expire_minutes,
        refresh_token_expire_days=settings.refresh_token_expire_days,
    )
    rate_limiter = RedisRateLimiter(redis_client)
    return LoginUserHandler(
        user_repository=repository,
        password_hasher=hasher,
        token_service=tokens,
        rate_limiter=rate_limiter,
        max_attempts=settings.login_rate_limit_attempts,
        window_seconds=settings.login_rate_limit_window_minutes * 60,
    )


def get_logout_user_handler(settings: Settings = Depends(get_settings)) -> LogoutUserHandler:
    tokens = TokenService(
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        access_token_expire_minutes=settings.access_token_expire_minutes,
        refresh_token_expire_days=settings.refresh_token_expire_days,
    )
    revocation_store = RedisTokenRevocationStore(redis_client)
    return LogoutUserHandler(token_service=tokens, revocation_store=revocation_store)
