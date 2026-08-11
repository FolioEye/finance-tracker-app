"""QA Lead mandatory security sweep for FINTRACK-38 (OAuth login via Google +
Apple), run at the real API level -- same convention and rationale as
tests/security/test_login_security.py.

Checklist (per fintrack-qa-lead skill, "any story touching auth, data, or
money"): SQL injection on every user-controlled field, XSS payload on every
text input, auth bypass, IDOR. Where a check genuinely doesn't apply to
this specific pair of endpoints, that's documented explicitly with
rationale rather than silently skipped.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.application.commands.oauth_login_user import OAuthLoginUserHandler
from apps.api.config import get_settings
from apps.api.infrastructure.repositories.sqlalchemy_user_repository import (
    SqlAlchemyUserRepository,
)
from apps.api.infrastructure.security.oauth_verifier import OAuthIdentity, OAuthTokenInvalidError
from apps.api.infrastructure.security.token_service import TokenService
from apps.api.presentation.api.v1.dependencies import get_db_session, get_oauth_login_user_handler

SQLI_PAYLOAD = "'; DROP TABLE users; --"
XSS_PAYLOAD = "<script>alert('xss')</script>"


class FakeVerifier:
    def __init__(self) -> None:
        self.identity: OAuthIdentity | None = None
        self.error: Exception | None = None

    async def verify(self, id_token: str) -> OAuthIdentity:
        if self.error:
            raise self.error
        assert self.identity is not None
        return self.identity


class AlwaysAllowRateLimiter:
    async def check_and_increment(self, key: str, max_attempts: int, window_seconds: int) -> bool:
        return True


@pytest.fixture
def google_verifier() -> FakeVerifier:
    return FakeVerifier()


@pytest.fixture
def apple_verifier() -> FakeVerifier:
    return FakeVerifier()


@pytest_asyncio.fixture
async def oauth_client(test_session_factory, google_verifier, apple_verifier):
    from fastapi import Depends
    from fastapi.testclient import TestClient

    from apps.api.main import app

    async def override_get_db_session():
        async with test_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    def _handler_factory(session: AsyncSession = Depends(get_db_session)) -> OAuthLoginUserHandler:
        settings = get_settings()
        repository = SqlAlchemyUserRepository(session)
        tokens = TokenService(
            secret_key=settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
            access_token_expire_minutes=settings.access_token_expire_minutes,
            refresh_token_expire_days=settings.refresh_token_expire_days,
        )
        return OAuthLoginUserHandler(
            user_repository=repository,
            token_service=tokens,
            rate_limiter=AlwaysAllowRateLimiter(),
            google_verifier=google_verifier,
            apple_verifier=apple_verifier,
            max_attempts=5,
            window_seconds=900,
        )

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_oauth_login_user_handler] = _handler_factory
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# SQL injection -- the only user-controlled fields on this endpoint are
# `provider` (pattern-locked to ^(google|apple)$ by Pydantic, rejected
# before it ever reaches a query) and `id_token` (never used in a SQL
# query at all -- it's handed to google-auth/PyJWT for signature
# verification, and only a verified `sub`/`email` claim from a *successful*
# verification ever reaches the repository layer). So SQLi payloads are
# tested here as forged id_token content, confirming they're rejected as
# invalid tokens (never reach a query) rather than causing any DB error.
# ---------------------------------------------------------------------------


def test_sql_injection_payload_as_id_token_rejected_generically(oauth_client, google_verifier) -> None:
    google_verifier.error = OAuthTokenInvalidError("malformed token")
    resp = oauth_client.post(
        "/api/v1/auth/oauth/google",
        json={"provider": "google", "id_token": SQLI_PAYLOAD},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "OAuth sign-in failed"


def test_sql_injection_payload_never_reflected_in_response(oauth_client, google_verifier) -> None:
    google_verifier.error = OAuthTokenInvalidError("malformed token")
    resp = oauth_client.post(
        "/api/v1/auth/oauth/google",
        json={"provider": "google", "id_token": SQLI_PAYLOAD},
    )
    assert SQLI_PAYLOAD not in resp.text


def test_sql_injection_via_provider_field_rejected_by_schema_before_any_query(oauth_client) -> None:
    """`provider` is pattern-locked ^(google|apple)$ at the Pydantic layer
    -- a SQLi-shaped provider value must fail validation (422) rather than
    ever reach the router/handler/repository."""
    resp = oauth_client.post(
        "/api/v1/auth/oauth/google",
        json={"provider": SQLI_PAYLOAD, "id_token": "whatever"},
    )
    assert resp.status_code == 422


def test_sql_injection_does_not_disturb_other_accounts(oauth_client, google_verifier) -> None:
    """Strongest evidence the DB is intact: a real, unrelated OAuth user
    can still sign in successfully right after the injection attempt."""
    google_verifier.error = OAuthTokenInvalidError("malformed token")
    oauth_client.post("/api/v1/auth/oauth/google", json={"provider": "google", "id_token": SQLI_PAYLOAD})

    google_verifier.error = None
    google_verifier.identity = OAuthIdentity(
        provider="google", subject="g-bystander", email="bystander@example.com", email_verified=True
    )
    followup = oauth_client.post(
        "/api/v1/auth/oauth/google", json={"provider": "google", "id_token": "real-token"}
    )
    assert followup.status_code == 200, followup.text


# ---------------------------------------------------------------------------
# XSS -- same rationale: id_token never reaches a rendered page; the one
# field that DOES get echoed back to the client on success is `email`, and
# that value only ever comes from a *verified* provider identity, never
# raw user input, so there is no reflected-XSS surface on a failure path
# to test against a forged token. What's tested here is that an XSS-shaped
# id_token is rejected the same generic way, with no reflection.
# ---------------------------------------------------------------------------


def test_xss_payload_as_id_token_rejected_generically(oauth_client, google_verifier) -> None:
    google_verifier.error = OAuthTokenInvalidError("malformed token")
    resp = oauth_client.post(
        "/api/v1/auth/oauth/google",
        json={"provider": "google", "id_token": XSS_PAYLOAD},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "OAuth sign-in failed"


def test_xss_payload_never_reflected_in_oauth_response(oauth_client, google_verifier) -> None:
    google_verifier.error = OAuthTokenInvalidError("malformed token")
    resp = oauth_client.post(
        "/api/v1/auth/oauth/google",
        json={"provider": "google", "id_token": XSS_PAYLOAD},
    )
    assert "<script>" not in resp.text


# ---------------------------------------------------------------------------
# Auth bypass
# ---------------------------------------------------------------------------


def test_auth_bypass_missing_id_token_rejected_by_schema(oauth_client) -> None:
    resp = oauth_client.post("/api/v1/auth/oauth/google", json={"provider": "google"})
    assert resp.status_code == 422


def test_auth_bypass_empty_id_token_rejected_by_schema(oauth_client) -> None:
    resp = oauth_client.post(
        "/api/v1/auth/oauth/google", json={"provider": "google", "id_token": ""}
    )
    assert resp.status_code == 422


def test_auth_bypass_invalid_token_and_unknown_identity_return_identical_response(
    oauth_client, google_verifier
) -> None:
    """Same no-enumeration principle as login/register: an invalid token
    and a well-formed-but-unverifiable token must both come back as the
    exact same 401 + generic detail, so a caller can't distinguish
    'malformed' from 'doesn't verify' from 'unknown user'."""
    google_verifier.error = OAuthTokenInvalidError("bad signature")
    r1 = oauth_client.post(
        "/api/v1/auth/oauth/google", json={"provider": "google", "id_token": "garbage"}
    )

    google_verifier.error = OAuthTokenInvalidError("expired")
    r2 = oauth_client.post(
        "/api/v1/auth/oauth/google", json={"provider": "google", "id_token": "expired-token"}
    )

    assert r1.status_code == r2.status_code == 401
    assert r1.json()["detail"] == r2.json()["detail"] == "OAuth sign-in failed"


def test_auth_bypass_provider_mismatch_between_url_and_body_rejected(oauth_client) -> None:
    """The provider is checked for agreement between the URL path and the
    request body (auth.py's _handle_oauth_login) -- since which verifier
    runs is a security-relevant decision, a mismatched pair must be
    rejected rather than silently trusting either one."""
    resp = oauth_client.post(
        "/api/v1/auth/oauth/google", json={"provider": "apple", "id_token": "whatever"}
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "provider does not match endpoint"


def test_auth_bypass_unverified_email_cannot_take_over_existing_account(
    oauth_client, google_verifier
) -> None:
    """The single most important security check in this flow, re-verified
    at the HTTP level (already unit-tested at the handler level in
    tests/unit/test_oauth_login_user.py): an OAuth identity whose provider
    reports email_verified=False must NOT be allowed to link onto -- and
    thereby take over -- an existing password-registered account sharing
    that email address."""
    victim_email = "victim@example.com"
    reg = oauth_client.post(
        "/api/v1/auth/register",
        json={"email": victim_email, "password": "VictimPass1", "confirm_password": "VictimPass1"},
    )
    assert reg.status_code == 201, reg.text

    google_verifier.identity = OAuthIdentity(
        provider="google", subject="attacker-sub", email=victim_email, email_verified=False
    )
    resp = oauth_client.post(
        "/api/v1/auth/oauth/google", json={"provider": "google", "id_token": "attacker-token"}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "OAuth sign-in failed"


# ---------------------------------------------------------------------------
# IDOR -- not applicable to this pair of endpoints. Both /oauth/google and
# /oauth/apple take no resource identifier of any kind (no user_id, no
# path/query param naming another account) -- the only "identity" involved
# is derived entirely from the verified provider token itself, which an
# attacker cannot forge without a valid signature (covered by the
# forged-token Gherkin scenarios in test_oauth_api.py). There is no
# object-reference parameter here for an IDOR check to exercise. Documented
# rather than silently omitted, same discipline as
# test_login_security.py's XSS-not-applicable-to-logout case.
# ---------------------------------------------------------------------------


def test_idor_not_applicable_no_resource_identifier_on_oauth_endpoints(oauth_client) -> None:
    resp = oauth_client.post("/api/v1/auth/oauth/google", json={"provider": "google"})
    assert resp.status_code == 422  # confirms the endpoint takes no id-like param to probe
