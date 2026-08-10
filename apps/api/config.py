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

    # Rate limiting -- registration (slowapi, IP-only)
    register_rate_limit_attempts: int = 5
    register_rate_limit_window_minutes: int = 15

    # Rate limiting -- login (Redis-backed, email+IP compound key; see
    # docs/adr/ADR-009-login-session-management.md)
    login_rate_limit_attempts: int = 5
    login_rate_limit_window_minutes: int = 15

    # OAuth (FINTRACK-42/43, ADR-016). Both are audience/client-id values,
    # not secrets -- verifying a Google/Apple ID token needs no server-side
    # client secret, only the expected audience to check the token's `aud`
    # claim against. apple_oauth_client_ids is comma-separated because
    # Apple issues a distinct client id per platform (web, iOS) that can
    # all sign in the same user -- see oauth_verifier.AppleIdTokenVerifier.
    google_oauth_client_id: str = ""
    apple_oauth_client_ids: str = ""

    # CORS. Comma-separated list of exact origins (scheme + host, no
    # trailing slash) allowed to call this API from a browser -- e.g.
    # "https://myfintrack.gtech45.com,https://staging.gtech45.com". Found
    # missing entirely during FINTRACK-38's Release Pro pass (2026-08-09):
    # apps/web's OAuth login POSTs the provider id_token to this API from
    # the browser, a cross-origin request (frontend on Hostinger, API on
    # Railway) -- with no CORSMiddleware configured at all, every such
    # request was always going to be silently blocked by the browser no
    # matter how correct the frontend/OAuth config was. Empty by default
    # so local dev/tests aren't forced to set it.
    cors_allowed_origins: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
