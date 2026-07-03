"""Application configuration loaded from environment variables (12-factor)."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "FinTrack API"
    environment: str = "development"
    debug: bool = False

    # Database
    database_url: str  # postgresql+asyncpg://user:pass@host:5432/dbname
    db_pool_min_size: int = 2
    db_pool_max_size: int = 10
    db_query_timeout_seconds: int = 5

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Auth / JWT -- secret must come from the environment, never hardcoded
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # Password policy
    bcrypt_rounds: int = 12
    password_min_length: int = 10

    # Rate limiting
    register_rate_limit_attempts: int = 5
    register_rate_limit_window_minutes: int = 15


@lru_cache
def get_settings() -> Settings:
    return Settings()
