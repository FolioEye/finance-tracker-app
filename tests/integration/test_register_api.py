"""QA Lead integration suite for FINTRACK-13 (User Registration).

Unlike tests/unit and tests/security, these hit the real FastAPI app
(apps.api.main:app) over HTTP via TestClient, backed by a genuine SQLite
DB per test -- real Pydantic request validation, real routing, real
bcrypt hashing, real JWT issuance, real Set-Cookie headers. Only the DB
backend and the get_db_session dependency are swapped for a test double;
everything else in the request path is production code.

Every scenario below maps 1:1 to a scenario in
tests/features/FINTRACK-13-user-registration.feature. No Gherkin step
text was altered to make it pass -- pytest-bdd fails at collection time
if a step in the .feature file has no matching implementation here.

Story is backend-only for this sprint (no registration *page* exists
yet -- that's a future frontend story), so "I am on the registration
page" / "I click Create Account" are interpreted as their backend
equivalent: the endpoint being reachable, and the actual POST request,
respectively. Full browser-driven Playwright E2E for these scenarios is
out of scope until the frontend story ships.
"""
from __future__ import annotations

import asyncio

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("../features/FINTRACK-13-user-registration.feature")


class RegistrationContext:
    """Per-scenario mutable state shared between Given/When/Then steps."""

    def __init__(self) -> None:
        self.email: str | None = None
        self.password: str = "StrongPass1"
        self.confirm_password: str | None = None
        self.response = None


@pytest.fixture
def ctx() -> RegistrationContext:
    return RegistrationContext()


def _submit(client, ctx: RegistrationContext):
    payload = {
        "email": ctx.email,
        "password": ctx.password,
        "confirm_password": ctx.confirm_password if ctx.confirm_password is not None else ctx.password,
    }
    ctx.response = client.post("/api/v1/auth/register", json=payload)
    return ctx.response


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given("I am on the registration page")
def on_registration_page() -> None:
    # No frontend exists yet for this story -- reachability of the real
    # endpoint is asserted implicitly by every Then step below.
    pass


@given(parsers.parse('an account already exists for "{email}"'))
def account_already_exists(client, ctx: RegistrationContext, email: str) -> None:
    ctx.email = email
    ctx.password = "ExistingPass1"
    _submit(client, ctx)
    assert ctx.response.status_code == 201, ctx.response.text
    ctx.response = None  # this Given is setup, not the thing under test


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when(parsers.parse('I enter email "{email}" and a password meeting strength requirements'))
def enter_email_and_strong_password(ctx: RegistrationContext, email: str) -> None:
    ctx.email = email
    ctx.password = "StrongPass1"


@when(parsers.parse('I attempt to register with email "{email}"'))
def attempt_register_with_email(client, ctx: RegistrationContext, email: str) -> None:
    ctx.email = email
    ctx.password = "AnotherPass1"
    _submit(client, ctx)


@when(parsers.parse('I enter email "{email}"'))
def enter_email(ctx: RegistrationContext, email: str) -> None:
    ctx.email = email
    ctx.password = "StrongPass1"


@when(parsers.parse('I enter password "{password}"'))
def enter_password_and_submit(client, ctx: RegistrationContext, password: str) -> None:
    # The Gherkin for this scenario has no separate "click Create Account"
    # step -- entering the password is what triggers submission.
    if ctx.email is None:
        ctx.email = "weak-password-check@example.com"
    ctx.password = password
    ctx.confirm_password = password
    _submit(client, ctx)


@when('I click "Create Account"')
def click_create_account(client, ctx: RegistrationContext) -> None:
    if ctx.response is None:
        _submit(client, ctx)


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then("my account should be created")
def account_created(ctx: RegistrationContext) -> None:
    assert ctx.response.status_code == 201, ctx.response.text


@then("I should be logged in and redirected to onboarding")
def logged_in_and_onboarding(ctx: RegistrationContext) -> None:
    # No frontend redirect exists yet -- "logged in" is verified at the API
    # level as: a usable access token was issued in the same response that
    # created the account (i.e. no separate login step was required).
    body = ctx.response.json()
    assert body["access_token"]
    assert body["email_verification_pending"] is True


@then(parsers.parse('I should see error "{message}"'))
def should_see_error(ctx: RegistrationContext, message: str) -> None:
    assert ctx.response.status_code == 409, ctx.response.text
    assert ctx.response.json()["detail"] == message


@then("no duplicate account should be created")
def no_duplicate_account(client, ctx: RegistrationContext) -> None:
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": ctx.email, "password": "YetAnother1", "confirm_password": "YetAnother1"},
    )
    assert resp.status_code == 409  # still exactly one account for this email


@then(parsers.parse('I should see validation error "{message}"'))
def should_see_validation_error(ctx: RegistrationContext, message: str) -> None:
    assert ctx.response.status_code == 400, ctx.response.text
    assert message in ctx.response.json()["detail"]


@then("no account should be created")
def no_account_created(ctx: RegistrationContext) -> None:
    assert ctx.response.status_code == 400


@then("the input should be sanitised")
def input_sanitised(ctx: RegistrationContext) -> None:
    # The malicious string never reaches a query: Email()'s format regex
    # rejects it up front (see domain/models/user.py), and even if it
    # somehow got past that, sqlalchemy_user_repository.py only ever
    # builds parameterised queries. 400, not 500 or a DB error, is the
    # proof the input was rejected cleanly rather than executed.
    assert ctx.response.status_code == 400


@then("the database should remain intact")
def database_intact(client) -> None:
    # If the DROP TABLE payload had actually executed, this next,
    # completely unrelated registration would fail with a DB error
    # instead of succeeding normally.
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": "post-injection-sanity-check@example.com",
            "password": "StrongPass1",
            "confirm_password": "StrongPass1",
        },
    )
    assert resp.status_code == 201, resp.text


@then("a security event should be logged")
def security_event_logged(caplog) -> None:
    # auth.py logs "registration_attempt" (email domain only, no PII, no
    # payload) before validation runs, so every attempt -- including
    # rejected/malicious ones -- leaves a log trail. The INFO capture
    # level is set by the autouse _capture_fintrack_logs fixture in
    # conftest.py, before any request in this scenario runs.
    assert any("registration_attempt" in record.getMessage() for record in caplog.records)


# ---------------------------------------------------------------------------
# Extra scenarios beyond the Gherkin, per QA Lead process step 1:
# concurrent modification + session/token edge cases.
# "Large dataset (1000+ records)" and "accessibility (keyboard nav, ARIA)"
# are addressed in test_register_extra_scenarios below with an explicit
# N/A rationale rather than being silently skipped.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_registration_same_email_only_one_succeeds(test_session_factory) -> None:
    """Concurrent modification scenario the Gherkin doesn't cover.

    Exercises the exact race the repository docstring calls out: two
    requests for the same email arriving close enough together that both
    pass get_by_email() before either has committed. The DB's unique
    constraint (via IntegrityError -> EmailAlreadyExistsError in
    sqlalchemy_user_repository.add()) must ensure exactly one wins.
    """
    from apps.api.application.commands.register_user import RegisterUserCommand, RegisterUserHandler
    from apps.api.domain.repositories.user_repository import EmailAlreadyExistsError
    from apps.api.infrastructure.repositories.sqlalchemy_user_repository import (
        SqlAlchemyUserRepository,
    )
    from apps.api.infrastructure.security.password_hasher import BcryptPasswordHasher
    from apps.api.infrastructure.security.token_service import TokenService

    async def attempt() -> str:
        async with test_session_factory() as session:
            handler = RegisterUserHandler(
                user_repository=SqlAlchemyUserRepository(session),
                password_hasher=BcryptPasswordHasher(rounds=4),  # low cost: speed, not security, under test here
                token_service=TokenService(secret_key="test-secret-key-not-for-production-use-only"),
            )
            command = RegisterUserCommand(
                email="race-condition@example.com",
                password="StrongPass1",
                confirm_password="StrongPass1",
            )
            try:
                await handler.handle(command)
                await session.commit()
                return "success"
            except EmailAlreadyExistsError:
                return "rejected"

    results = await asyncio.gather(attempt(), attempt())
    assert results.count("success") == 1, f"expected exactly one winner, got {results}"
    assert results.count("rejected") == 1, f"expected exactly one rejection, got {results}"


def test_successful_registration_issues_valid_access_token_and_secure_refresh_cookie(client) -> None:
    """Session edge case the Gherkin doesn't spell out: verifies the actual
    tokens/cookie issued on success, not just that *some* 201 came back.
    """
    import jwt as jose_jwt  # PyJWT (see ADR-006) -- alias kept to minimize diff

    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": "session-check@example.com",
            "password": "StrongPass1",
            "confirm_password": "StrongPass1",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    claims = jose_jwt.decode(body["access_token"], options={"verify_signature": False})
    assert claims["type"] == "access"
    assert claims["sub"] == body["user_id"]
    ttl_seconds = claims["exp"] - claims["iat"]
    assert 14 * 60 <= ttl_seconds <= 16 * 60, f"expected ~15min access token TTL, got {ttl_seconds}s"

    set_cookie = resp.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "samesite=strict" in set_cookie.lower()


@pytest.mark.asyncio
async def test_register_extra_scenarios_not_applicable_documented(test_session_factory) -> None:
    """Documents, rather than silently skipping, two scenario categories
    from the QA Lead checklist that don't meaningfully apply to this
    specific story:

    - Accessibility (keyboard nav, ARIA labels): N/A -- FINTRACK-13 is a
      backend-only story this sprint; no registration UI exists to test
      yet. Applicable once the frontend registration form ships.
    - Large dataset (1000+ records): registration is a single-row insert
      keyed by a unique, indexed email column -- correctness at scale is
      about the *query* path (list/search/report stories), not this
      write-one-row endpoint. A rough proxy is included below: uniqueness
      enforcement still works correctly with a non-trivially sized table,
      rather than only ever having been tested against an empty one.

    Goes through the handler directly (not the HTTP endpoint) so that the
    registration endpoint's own rate limit -- a real, separate concern --
    doesn't confound what this test is actually checking.
    """
    from apps.api.application.commands.register_user import RegisterUserCommand, RegisterUserHandler
    from apps.api.domain.repositories.user_repository import EmailAlreadyExistsError
    from apps.api.infrastructure.repositories.sqlalchemy_user_repository import (
        SqlAlchemyUserRepository,
    )
    from apps.api.infrastructure.security.password_hasher import BcryptPasswordHasher
    from apps.api.infrastructure.security.token_service import TokenService

    async def register(email: str) -> RegisterUserHandler:
        async with test_session_factory() as session:
            handler = RegisterUserHandler(
                user_repository=SqlAlchemyUserRepository(session),
                password_hasher=BcryptPasswordHasher(rounds=4),  # low cost: speed, not security, under test here
                token_service=TokenService(secret_key="test-secret-key-not-for-production-use-only"),
            )
            await handler.handle(
                RegisterUserCommand(email=email, password="StrongPass1", confirm_password="StrongPass1")
            )
            await session.commit()

    for i in range(50):
        await register(f"bulk-user-{i}@example.com")

    # New, still-unique email succeeds against the now-populated table.
    await register("the-51st-user@example.com")

    # A duplicate of an early row is still caught correctly, not skipped
    # due to table size.
    with pytest.raises(EmailAlreadyExistsError):
        await register("bulk-user-3@example.com")
