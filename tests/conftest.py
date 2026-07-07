"""Shared pytest fixtures.

tests/unit and tests/security (Tech Lead's original suite) fake external
dependencies at the port boundary -- no real DB or network calls there.

tests/integration and the API-level tests/security additions (QA Lead,
FINTRACK-13) are real integration tests: a genuine in-memory SQLite DB
behind SQLAlchemy's async engine, and FastAPI's TestClient driving actual
HTTP requests through the real router, real Pydantic validation, real
bcrypt hashing, and real JWT issuance. Only the DB backend (SQLite instead
of Postgres), the Redis backend (fakeredis instead of real Redis, added
for FINTRACK-14), and the FastAPI dependency wiring are swapped for tests.
"""
import os

# Test-only defaults so Settings() can construct without a real .env file.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-production-use-only")

import pytest
import pytest_asyncio
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

# fakeredis stands in for Redis the same way aiosqlite stands in for
# Postgres above: FINTRACK-14's rate limiter and token-revocation store
# both depend on Redis, and tests shouldn't depend on CI's real redis:7
# service being reachable or starting from a clean slate any more than
# they depend on the real Postgres service. This patch MUST happen at
# module level (not inside a fixture) and before anything else in this
# process imports apps.api.main / dependencies.py, because
# presentation/api/v1/dependencies.py does
# `from apps.api.infrastructure.cache.redis_client import redis_client` --
# a `from X import Y` binds Y's value at that import's time, so this only
# takes effect for every downstream import if it runs first.
import fakeredis.aioredis

import apps.api.infrastructure.cache.redis_client as _redis_client_module

_redis_client_module.redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)


# UserModel's id column uses the Postgres-specific UUID type. SQLite has no
# native UUID type, so teach SQLAlchemy's DDL compiler to render it as a
# fixed-width CHAR column for the sqlite dialect only. Test-only shim --
# nothing about apps/api/infrastructure/database/models.py changes.
@compiles(PGUUID, "sqlite")
def _compile_uuid_sqlite(element, compiler, **kw):  # pragma: no cover - DDL compile hook
    return "CHAR(32)"


@pytest_asyncio.fixture
async def test_engine():
    """Fresh in-memory SQLite DB per test, with the real ORM schema applied."""
    from apps.api.infrastructure.database.models import Base

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def test_session_factory(test_engine):
    return async_sessionmaker(test_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def client(test_session_factory):
    """FastAPI TestClient wired to the real app, with only get_db_session
    overridden to use the in-memory test DB instead of the (unreachable in
    this sandbox) Postgres instance the app is configured for by default.
    """
    from fastapi.testclient import TestClient

    from apps.api.main import app
    from apps.api.presentation.api.v1.dependencies import get_db_session

    async def override_get_db_session():
        async with test_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_session] = override_get_db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """slowapi's Limiter is a module-level singleton in auth.py, shared
    across every test in the process. Reset its storage before each test
    so registration attempts in one test don't get rate-limited by state
    left over from a previous, unrelated test.
    """
    from apps.api.presentation.api.v1.auth import limiter

    limiter.reset()
    yield


@pytest_asyncio.fixture(autouse=True)
async def _flush_redis():
    """The fake Redis client is a process-wide singleton (real Redis in
    production is too) -- flush it before each test so rate-limit counters
    and revoked-token entries from one test don't bleed into another,
    exactly like _reset_rate_limiter does for slowapi's in-memory store.
    """
    from apps.api.infrastructure.cache.redis_client import redis_client

    await redis_client.flushdb()
    yield


@pytest.fixture(autouse=True)
def _capture_fintrack_logs(caplog):
    """caplog's handler defaults to WARNING; auth.py logs registration
    attempts at INFO. Raise the captured level before any test body runs,
    so tests asserting on log output (e.g. the security-event-logged
    Gherkin step) don't depend on step/assertion ordering within a test.
    """
    caplog.set_level("INFO", logger="fintrack.auth")
    yield
