"""Unit tests for OAuthLoginUserHandler. External deps (verifiers, repo,
rate limiter) faked at the port boundary per constraint matrix -- no real
Google/Apple network calls, no real DB.
"""
from __future__ import annotations

import uuid

import pytest

from apps.api.application.commands.oauth_login_user import (
    OAuthLoginCommand,
    OAuthLoginError,
    OAuthLoginUserHandler,
)
from apps.api.domain.models.user import Email, User
from apps.api.domain.repositories.user_repository import EmailAlreadyExistsError
from apps.api.infrastructure.security.oauth_verifier import (
    OAuthIdentity,
    OAuthProviderUnavailableError,
    OAuthTokenInvalidError,
)
from apps.api.infrastructure.security.rate_limiter import RateLimitExceededError
from apps.api.infrastructure.security.token_service import TokenPair
from tests.unit.test_login_logout_user import AlwaysAllowRateLimiter, CountingRateLimiter


class FakeOAuthUserRepository:
    """Duck-typed fake implementing the full UserRepository port, including
    the two OAuth-specific methods -- same convention as
    tests/unit/test_register_user.py's FakeUserRepository."""

    def __init__(self) -> None:
        self.by_email: dict[str, User] = {}
        self.by_oauth: dict[tuple[str, str], User] = {}
        self.added: list[User] = []
        self.linked: list[tuple[uuid.UUID, str, str]] = []

    async def get_by_email(self, email: Email):
        return self.by_email.get(str(email))

    async def get_by_id(self, user_id: uuid.UUID):
        for u in self.by_email.values():
            if u.id == user_id:
                return u
        return None

    async def get_by_oauth_identity(self, provider: str, subject: str):
        return self.by_oauth.get((provider, subject))

    async def add(self, user: User) -> None:
        if str(user.email) in self.by_email:
            raise EmailAlreadyExistsError("An account with this email already exists")
        self.by_email[str(user.email)] = user
        if user.oauth_provider and user.oauth_subject:
            self.by_oauth[(user.oauth_provider, user.oauth_subject)] = user
        self.added.append(user)

    async def link_oauth_identity(self, user_id: uuid.UUID, provider: str, subject: str) -> None:
        user = await self.get_by_id(user_id)
        if user is None:
            raise ValueError(f"user {user_id} not found")
        user.oauth_provider = provider
        user.oauth_subject = subject
        self.by_oauth[(provider, subject)] = user
        self.linked.append((user_id, provider, subject))


class FakeTokenService:
    def issue_pair(self, user_id: uuid.UUID) -> TokenPair:
        return TokenPair(
            access_token=f"fake-access-{user_id}",
            refresh_token=f"fake-refresh-{user_id}",
            access_token_expires_in_seconds=900,
        )


class FakeGoogleVerifier:
    def __init__(self, identity: OAuthIdentity | None = None, error: Exception | None = None) -> None:
        self._identity = identity
        self._error = error
        self.calls = 0

    async def verify(self, id_token: str) -> OAuthIdentity:
        self.calls += 1
        if self._error:
            raise self._error
        assert self._identity is not None
        return self._identity


class FakeAppleVerifier(FakeGoogleVerifier):
    """Same shape as FakeGoogleVerifier -- both verifiers expose a single
    async verify(id_token) method, so one fake class covers both."""


def _handler(repo, tokens, google_verifier, apple_verifier, rate_limiter=None) -> OAuthLoginUserHandler:
    return OAuthLoginUserHandler(
        user_repository=repo,
        token_service=tokens,
        rate_limiter=rate_limiter or AlwaysAllowRateLimiter(),
        google_verifier=google_verifier,
        apple_verifier=apple_verifier,
        max_attempts=5,
        window_seconds=900,
    )


@pytest.fixture
def repo() -> FakeOAuthUserRepository:
    return FakeOAuthUserRepository()


@pytest.fixture
def tokens() -> FakeTokenService:
    return FakeTokenService()


@pytest.mark.asyncio
async def test_new_google_user_is_created(repo, tokens) -> None:
    """Happy path: first-ever Google sign-in creates a brand-new OAuth-only user."""
    identity = OAuthIdentity(provider="google", subject="g-sub-1", email="new@example.com", email_verified=True)
    handler = _handler(repo, tokens, FakeGoogleVerifier(identity), FakeAppleVerifier())

    result = await handler.handle(
        OAuthLoginCommand(provider="google", id_token="whatever", client_ip="1.2.3.4")
    )

    assert result.is_new_user is True
    assert str(result.user.email) == "new@example.com"
    assert result.user.password_hash is None
    assert result.user.oauth_provider == "google"
    assert result.tokens.access_token


@pytest.mark.asyncio
async def test_returning_oauth_user_looked_up_by_identity_not_email(repo, tokens) -> None:
    """A second login with the same (provider, subject) must hit the
    existing-user path, not create a duplicate."""
    identity = OAuthIdentity(provider="apple", subject="a-sub-1", email="user@example.com", email_verified=True)
    handler = _handler(repo, tokens, FakeGoogleVerifier(), FakeAppleVerifier(identity))

    first = await handler.handle(OAuthLoginCommand(provider="apple", id_token="t1", client_ip="1.2.3.4"))
    second = await handler.handle(OAuthLoginCommand(provider="apple", id_token="t2", client_ip="1.2.3.4"))

    assert first.is_new_user is True
    assert second.is_new_user is False
    assert first.user.id == second.user.id
    assert len(repo.added) == 1


@pytest.mark.asyncio
async def test_verified_email_links_to_existing_password_account(repo, tokens) -> None:
    """Security-critical path: a verified-email OAuth login matching an
    existing password-based account links rather than duplicates."""
    existing = User.new(email=Email("shared@example.com"), password_hash="hashed:whatever")
    repo.by_email[str(existing.email)] = existing

    identity = OAuthIdentity(provider="google", subject="g-sub-2", email="shared@example.com", email_verified=True)
    handler = _handler(repo, tokens, FakeGoogleVerifier(identity), FakeAppleVerifier())

    result = await handler.handle(
        OAuthLoginCommand(provider="google", id_token="whatever", client_ip="1.2.3.4")
    )

    assert result.is_new_user is False
    assert result.user.id == existing.id
    assert repo.linked == [(existing.id, "google", "g-sub-2")]


@pytest.mark.asyncio
async def test_unverified_email_does_not_link_to_existing_account(repo, tokens) -> None:
    """The single most important security check in this flow: an
    unverified provider email must NOT be allowed to take over an
    existing account just by claiming the same address."""
    existing = User.new(email=Email("shared@example.com"), password_hash="hashed:whatever")
    repo.by_email[str(existing.email)] = existing

    identity = OAuthIdentity(provider="google", subject="g-sub-3", email="shared@example.com", email_verified=False)
    handler = _handler(repo, tokens, FakeGoogleVerifier(identity), FakeAppleVerifier())

    with pytest.raises(OAuthLoginError):
        await handler.handle(
            OAuthLoginCommand(provider="google", id_token="whatever", client_ip="1.2.3.4")
        )

    assert repo.linked == []


@pytest.mark.asyncio
async def test_invalid_token_raises_generic_oauth_login_error(repo, tokens) -> None:
    handler = _handler(
        repo, tokens, FakeGoogleVerifier(error=OAuthTokenInvalidError("bad sig")), FakeAppleVerifier()
    )

    with pytest.raises(OAuthLoginError):
        await handler.handle(
            OAuthLoginCommand(provider="google", id_token="garbage", client_ip="1.2.3.4")
        )


@pytest.mark.asyncio
async def test_provider_unavailable_propagates_distinctly_for_503_mapping(repo, tokens) -> None:
    """OAuthProviderUnavailableError must NOT be swallowed into
    OAuthLoginError -- the API layer needs to tell a transient provider
    outage (503) apart from a genuinely invalid token (401)."""
    handler = _handler(
        repo, tokens, FakeGoogleVerifier(error=OAuthProviderUnavailableError("jwks down")), FakeAppleVerifier()
    )

    with pytest.raises(OAuthProviderUnavailableError):
        await handler.handle(
            OAuthLoginCommand(provider="google", id_token="whatever", client_ip="1.2.3.4")
        )


@pytest.mark.asyncio
async def test_rate_limit_checked_before_token_verification(repo, tokens) -> None:
    """Rate limit must short-circuit before the (expensive, external)
    verifier is ever called -- same principle as LoginUserHandler checking
    the limiter before any DB call."""
    rate_limiter = CountingRateLimiter()
    google_verifier = FakeGoogleVerifier(
        OAuthIdentity(provider="google", subject="g-1", email="x@example.com", email_verified=True)
    )
    handler = _handler(repo, tokens, google_verifier, FakeAppleVerifier(), rate_limiter=rate_limiter)

    for _ in range(5):
        await handler.handle(
            OAuthLoginCommand(provider="google", id_token="t", client_ip="9.9.9.9")
        )

    with pytest.raises(RateLimitExceededError):
        await handler.handle(
            OAuthLoginCommand(provider="google", id_token="t", client_ip="9.9.9.9")
        )

    # 5 allowed calls actually verified a token; the 6th (rate-limited)
    # must not have reached the verifier at all.
    assert google_verifier.calls == 5
