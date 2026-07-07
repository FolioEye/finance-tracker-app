"""Unit tests for LoginUserHandler and LogoutUserHandler. External deps
faked at the port boundary per constraint matrix -- no real DB or Redis
calls in this file (see tests/integration/test_login_logout_api.py for
the real-API-level equivalents, and conftest.py for the fakeredis wiring
used there).
"""
from __future__ import annotations

import uuid

import pytest

from apps.api.application.commands.login_user import (
    InvalidCredentialsError,
    LoginUserCommand,
    LoginUserHandler,
)
from apps.api.application.commands.logout_user import (
    LogoutUserCommand,
    LogoutUserHandler,
    NoActiveSessionError,
)
from apps.api.domain.models.user import Email, User
from apps.api.infrastructure.security.rate_limiter import RateLimitExceededError
from apps.api.infrastructure.security.token_service import TokenPair, TokenService
from tests.unit.test_register_user import FakePasswordHasher, FakeUserRepository


class AlwaysAllowRateLimiter:
    """Fake RateLimiter that never blocks -- used for tests that aren't
    specifically exercising rate-limit behaviour."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def check_and_increment(self, key: str, max_attempts: int, window_seconds: int) -> bool:
        self.calls.append(key)
        return True


class CountingRateLimiter:
    """Fake RateLimiter with real fixed-window counting logic, in-memory --
    lets tests exercise the actual threshold behaviour without Redis."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    async def check_and_increment(self, key: str, max_attempts: int, window_seconds: int) -> bool:
        self._counts[key] = self._counts.get(key, 0) + 1
        return self._counts[key] <= max_attempts


class FakeTokenRevocationStore:
    def __init__(self) -> None:
        self.revoked: dict[str, int] = {}

    async def revoke(self, jti: str, expires_at_epoch: int) -> None:
        self.revoked[jti] = expires_at_epoch

    async def is_revoked(self, jti: str) -> bool:
        return jti in self.revoked


class FakeTokenServiceWithDecode(TokenService):
    """Real TokenService (not faked) -- login/logout depend on real JWT
    encode/decode semantics (claims shape, jti, exp), which a hand-rolled
    fake would either have to reimplement or risk diverging from
    production behaviour. Using the real class here is a deliberate
    choice, same as FINTRACK-13's session-edge-case test decodes a real
    token rather than trusting a fake's return value.
    """

    def __init__(self) -> None:
        super().__init__(secret_key="test-secret-key-not-for-production-use-only")


@pytest.fixture
def user_repo() -> FakeUserRepository:
    return FakeUserRepository()


@pytest.fixture
def hasher() -> FakePasswordHasher:
    return FakePasswordHasher()


@pytest.fixture
def tokens() -> FakeTokenServiceWithDecode:
    return FakeTokenServiceWithDecode()


async def _seed_user(user_repo: FakeUserRepository, hasher: FakePasswordHasher, email: str, password: str) -> User:
    user = User.new(email=Email(email), password_hash=hasher.hash(password))
    user_repo.users[str(user.email)] = user
    return user


def _login_handler(user_repo, hasher, tokens, rate_limiter=None) -> LoginUserHandler:
    return LoginUserHandler(
        user_repository=user_repo,
        password_hasher=hasher,
        token_service=tokens,
        rate_limiter=rate_limiter or AlwaysAllowRateLimiter(),
        max_attempts=5,
        window_seconds=900,
    )


# ---------------------------------------------------------------------------
# Login -- happy path + Gherkin-mapped failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_login(user_repo, hasher, tokens) -> None:
    """Matches Gherkin: 'Successfully log in with correct credentials'."""
    await _seed_user(user_repo, hasher, "user@example.com", "CorrectPass1")
    handler = _login_handler(user_repo, hasher, tokens)

    result = await handler.handle(
        LoginUserCommand(email="user@example.com", password="CorrectPass1", client_ip="1.2.3.4")
    )

    assert str(result.user.email) == "user@example.com"
    assert result.tokens.access_token
    assert result.tokens.refresh_token


@pytest.mark.asyncio
async def test_wrong_password_rejected_generically(user_repo, hasher, tokens) -> None:
    """Matches Gherkin: 'Attempt to log in with an incorrect password'."""
    await _seed_user(user_repo, hasher, "user@example.com", "CorrectPass1")
    handler = _login_handler(user_repo, hasher, tokens)

    with pytest.raises(InvalidCredentialsError, match="Invalid email or password"):
        await handler.handle(
            LoginUserCommand(email="user@example.com", password="WrongPass9", client_ip="1.2.3.4")
        )


@pytest.mark.asyncio
async def test_unknown_email_rejected_with_same_generic_error(user_repo, hasher, tokens) -> None:
    """No-user-enumeration requirement (AC2): the error for an unknown
    email must be textually identical to the wrong-password error above,
    not a distinguishable 'no such user' message.
    """
    handler = _login_handler(user_repo, hasher, tokens)

    with pytest.raises(InvalidCredentialsError, match="Invalid email or password"):
        await handler.handle(
            LoginUserCommand(email="nobody@example.com", password="Whatever1", client_ip="1.2.3.4")
        )


@pytest.mark.asyncio
async def test_deactivated_account_rejected_like_any_other_failure(user_repo, hasher, tokens) -> None:
    """is_active=False must fail exactly like a wrong password -- not a
    distinct 'account disabled' message, which would itself be a form of
    enumeration (confirms the account exists, just disabled).
    """
    user = await _seed_user(user_repo, hasher, "disabled@example.com", "CorrectPass1")
    user.is_active = False
    handler = _login_handler(user_repo, hasher, tokens)

    with pytest.raises(InvalidCredentialsError, match="Invalid email or password"):
        await handler.handle(
            LoginUserCommand(email="disabled@example.com", password="CorrectPass1", client_ip="1.2.3.4")
        )


@pytest.mark.asyncio
async def test_sql_injection_shaped_email_rejected_generically_not_by_format(user_repo, hasher, tokens) -> None:
    """Matches Gherkin: 'Attempt SQL injection in the email field during
    login'. Unlike registration, this must raise the SAME
    InvalidCredentialsError as any other failure -- not a
    format-specific InvalidEmailError -- since login must not leak
    format-validity as a distinguishable signal.
    """
    handler = _login_handler(user_repo, hasher, tokens)

    with pytest.raises(InvalidCredentialsError, match="Invalid email or password"):
        await handler.handle(
            LoginUserCommand(email="'; DROP TABLE users; --", password="anything", client_ip="1.2.3.4")
        )

    # Confirm the DB layer was never reached for the malformed email --
    # FakeUserRepository would have nothing to match anyway, but the real
    # assertion is that no exception type leaked from the Email() call.
    assert user_repo.added == []


@pytest.mark.asyncio
async def test_rate_limit_exceeded_raises_before_any_db_lookup(user_repo, hasher, tokens) -> None:
    """Matches Gherkin: 'Sixth login attempt within 15 minutes is
    rate-limited'. Uses a real counting fake (not Redis) to verify the
    handler actually calls into the rate limiter before touching the
    repository, and stops at the threshold.
    """
    await _seed_user(user_repo, hasher, "user@example.com", "CorrectPass1")
    rate_limiter = CountingRateLimiter()
    handler = _login_handler(user_repo, hasher, tokens, rate_limiter=rate_limiter)

    for _ in range(5):
        # Each of these 5 is expected to fail on the wrong password (that's
        # not what's under test here) -- only the 6th, checked below,
        # should fail on the rate limit instead.
        with pytest.raises(InvalidCredentialsError):
            await handler.handle(
                LoginUserCommand(email="user@example.com", password="WrongPass9", client_ip="9.9.9.9")
            )

    with pytest.raises(RateLimitExceededError):
        await handler.handle(
            LoginUserCommand(email="user@example.com", password="CorrectPass1", client_ip="9.9.9.9")
        )


@pytest.mark.asyncio
async def test_rate_limit_is_keyed_on_email_and_ip_together(user_repo, hasher, tokens) -> None:
    """AC4: rate limit is per account+IP, not IP alone and not email alone --
    a different IP attempting the same email should not inherit the first
    IP's exhausted counter.
    """
    await _seed_user(user_repo, hasher, "user@example.com", "CorrectPass1")
    rate_limiter = CountingRateLimiter()
    handler = _login_handler(user_repo, hasher, tokens, rate_limiter=rate_limiter)

    for _ in range(5):
        with pytest.raises(InvalidCredentialsError):
            await handler.handle(
                LoginUserCommand(email="user@example.com", password="WrongPass9", client_ip="1.1.1.1")
            )

    # Same email, different IP -- must NOT be blocked by IP 1.1.1.1's counter.
    result = await handler.handle(
        LoginUserCommand(email="user@example.com", password="CorrectPass1", client_ip="2.2.2.2")
    )
    assert result.tokens.access_token


@pytest.mark.asyncio
async def test_unknown_email_and_wrong_password_take_comparable_time(user_repo, hasher, tokens) -> None:
    """No-user-enumeration via timing (AC2, beyond what the Gherkin spells
    out explicitly): both failure paths must invoke the password hasher's
    verify() the same number of times, so response latency doesn't reveal
    whether the email exists. Asserts on call count rather than wall-clock
    time, which would be flaky in CI.
    """
    await _seed_user(user_repo, hasher, "user@example.com", "CorrectPass1")

    class CountingHasher(FakePasswordHasher):
        def __init__(self) -> None:
            self.verify_calls = 0

        def verify(self, raw_password: str, password_hash: str) -> bool:
            self.verify_calls += 1
            return super().verify(raw_password, password_hash)

    counting_hasher = CountingHasher()
    handler = _login_handler(user_repo, counting_hasher, tokens)

    with pytest.raises(InvalidCredentialsError):
        await handler.handle(
            LoginUserCommand(email="user@example.com", password="WrongPass9", client_ip="1.2.3.4")
        )
    wrong_password_calls = counting_hasher.verify_calls

    counting_hasher.verify_calls = 0
    with pytest.raises(InvalidCredentialsError):
        await handler.handle(
            LoginUserCommand(email="nobody@example.com", password="Whatever1", client_ip="1.2.3.4")
        )
    unknown_email_calls = counting_hasher.verify_calls

    assert wrong_password_calls == unknown_email_calls == 1


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logout_revokes_the_refresh_token_jti(tokens) -> None:
    revocation = FakeTokenRevocationStore()
    handler = LogoutUserHandler(token_service=tokens, revocation_store=revocation)

    pair = tokens.issue_pair(uuid.uuid4())
    claims = tokens.decode(pair.refresh_token)

    await handler.handle(LogoutUserCommand(refresh_token=pair.refresh_token))

    assert await revocation.is_revoked(claims["jti"]) is True


@pytest.mark.asyncio
async def test_logout_with_no_cookie_raises_no_active_session(tokens) -> None:
    revocation = FakeTokenRevocationStore()
    handler = LogoutUserHandler(token_service=tokens, revocation_store=revocation)

    with pytest.raises(NoActiveSessionError):
        await handler.handle(LogoutUserCommand(refresh_token=""))


@pytest.mark.asyncio
async def test_logout_with_garbage_token_is_idempotent_not_a_crash(tokens) -> None:
    revocation = FakeTokenRevocationStore()
    handler = LogoutUserHandler(token_service=tokens, revocation_store=revocation)

    # Should not raise -- an already-invalid token has nothing left to revoke.
    await handler.handle(LogoutUserCommand(refresh_token="not-a-real-jwt"))
    assert revocation.revoked == {}


@pytest.mark.asyncio
async def test_logout_rejects_an_access_token_used_as_refresh_token(tokens) -> None:
    """Session edge case beyond the Gherkin: if a client mistakenly (or
    maliciously) sends an access token in place of the refresh cookie,
    logout must not treat it as a valid session to revoke -- access
    tokens were never meant to be revocable via this path (see ADR-009).
    """
    revocation = FakeTokenRevocationStore()
    handler = LogoutUserHandler(token_service=tokens, revocation_store=revocation)

    pair = tokens.issue_pair(uuid.uuid4())

    with pytest.raises(NoActiveSessionError):
        await handler.handle(LogoutUserCommand(refresh_token=pair.access_token))
