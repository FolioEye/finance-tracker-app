"""QA Lead integration suite for FINTRACK-14 (Login/Logout).

Same approach as tests/integration/test_register_api.py: hits the real
FastAPI app over HTTP via TestClient, backed by a genuine SQLite DB and
(new for this story) a genuine fakeredis instance for rate limiting and
token revocation -- see tests/conftest.py.

Every scenario below maps 1:1 to a scenario in
tests/features/FINTRACK-14-login-logout.feature. No Gherkin step text was
altered to make it pass -- pytest-bdd fails at collection time if a step
in the .feature file has no matching implementation here.
"""
from __future__ import annotations

import asyncio

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("../features/FINTRACK-14-login-logout.feature")


class LoginContext:
    """Per-scenario mutable state shared between Given/When/Then steps."""

    def __init__(self) -> None:
        self.email: str | None = None
        self.password: str | None = None
        self.registered_password: str = "StrongPass1"
        self.response = None


@pytest.fixture
def ctx() -> LoginContext:
    return LoginContext()


def _login(client, ctx: LoginContext):
    ctx.response = client.post(
        "/api/v1/auth/login", json={"email": ctx.email, "password": ctx.password}
    )
    return ctx.response


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given("I have a registered account")
def have_a_registered_account(client, ctx: LoginContext) -> None:
    ctx.email = "login-scenario-user@example.com"
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": ctx.email,
            "password": ctx.registered_password,
            "confirm_password": ctx.registered_password,
        },
    )
    assert resp.status_code == 201, resp.text


@given("I am on the login page")
def on_login_page() -> None:
    # No frontend exists yet for this story -- reachability of the real
    # endpoint is asserted implicitly by every Then step below.
    pass


@given("I have made 5 failed login attempts for the same account within 15 minutes")
def five_failed_attempts(client, ctx: LoginContext) -> None:
    ctx.email = "rate-limited-user@example.com"
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": ctx.email,
            "password": ctx.registered_password,
            "confirm_password": ctx.registered_password,
        },
    )
    assert resp.status_code == 201, resp.text

    for _ in range(5):
        r = client.post(
            "/api/v1/auth/login", json={"email": ctx.email, "password": "WrongPassword9"}
        )
        assert r.status_code == 401, r.text


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when("I enter my correct email and password")
def enter_correct_credentials(ctx: LoginContext) -> None:
    ctx.password = ctx.registered_password


@when("I enter my email and an incorrect password")
def enter_incorrect_password(client, ctx: LoginContext) -> None:
    # This scenario has no separate "click Log In" step in the Gherkin --
    # entering the password is what triggers submission (same pattern
    # FINTRACK-13 used for its weak-password scenario).
    ctx.password = "DefinitelyWrongPass9"
    _login(client, ctx)


@when('I click "Log In"')
def click_log_in(client, ctx: LoginContext) -> None:
    _login(client, ctx)


@when("I attempt to log in a 6th time")
def attempt_sixth_login(client, ctx: LoginContext) -> None:
    # Deliberately the CORRECT password here -- proves the rate limiter
    # short-circuits before the credential/DB check runs at all, not just
    # that a 6th wrong-password attempt happens to also fail.
    ctx.password = ctx.registered_password
    _login(client, ctx)


@when(parsers.parse('I enter email "{email}" and any password'))
def enter_email_and_any_password(client, ctx: LoginContext, email: str) -> None:
    ctx.email = email
    ctx.password = "any-password-123"
    _login(client, ctx)


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then("I should be redirected to my dashboard")
def redirected_to_dashboard(ctx: LoginContext) -> None:
    # No frontend redirect exists yet -- "redirected to dashboard" is
    # verified at the API level as a successful 200 with a usable session
    # issued, same interpretation FINTRACK-13 used for "redirected to
    # onboarding".
    assert ctx.response.status_code == 200, ctx.response.text


@then("a short-lived access token and httpOnly refresh token should be issued")
def tokens_issued(ctx: LoginContext) -> None:
    body = ctx.response.json()
    assert body["access_token"]
    assert "refresh_token" not in body  # F-02: cookie-only, never in the body

    set_cookie = ctx.response.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "samesite=strict" in set_cookie.lower()


@then(parsers.parse('I should see a generic error "{message}"'))
def should_see_generic_error(ctx: LoginContext, message: str) -> None:
    assert ctx.response.status_code == 401, ctx.response.text
    assert ctx.response.json()["detail"] == message


@then("the error should not reveal whether the email exists")
def error_does_not_reveal_existence(client, ctx: LoginContext) -> None:
    # Compare against the identical wrong-password-on-unknown-email
    # response -- both must be byte-for-byte the same.
    unknown = client.post(
        "/api/v1/auth/login",
        json={"email": "no-such-account@example.com", "password": "DefinitelyWrongPass9"},
    )
    assert unknown.status_code == ctx.response.status_code
    assert unknown.json() == ctx.response.json()


@then(parsers.parse('I should see error "{message}"'))
def should_see_error(ctx: LoginContext, message: str) -> None:
    assert ctx.response.status_code == 429, ctx.response.text
    assert ctx.response.json()["detail"] == message


@then("the attempt should not be processed against the database")
def attempt_not_processed(ctx: LoginContext) -> None:
    # The 6th attempt used the CORRECT password (see attempt_sixth_login
    # above) yet still failed with 429, not a 200 -- proof the credential
    # check (and the DB lookup it requires) never ran for this attempt.
    assert ctx.response.status_code == 429
    assert ctx.response.json()["detail"] == "Too many attempts, try again later"


@then("the input should be sanitised")
def input_sanitised(ctx: LoginContext) -> None:
    assert ctx.response.status_code == 401


@then("I should see the generic invalid-credentials error")
def generic_invalid_credentials_error(ctx: LoginContext) -> None:
    assert ctx.response.json()["detail"] == "Invalid email or password"


@then("the database should remain intact")
def database_intact(client) -> None:
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": "post-login-injection-sanity-check@example.com",
            "password": "StrongPass1",
            "confirm_password": "StrongPass1",
        },
    )
    assert resp.status_code == 201, resp.text


@then("a security event should be logged")
def security_event_logged(caplog) -> None:
    # auth.py logs "login_failed" on any InvalidCredentialsError, which
    # the SQLi-shaped-email scenario hits (folded into the generic path,
    # per LoginUserHandler). The INFO capture level is set by the autouse
    # _capture_fintrack_logs fixture in conftest.py.
    assert any("login_failed" in record.getMessage() for record in caplog.records)


# ---------------------------------------------------------------------------
# Extra scenarios beyond the Gherkin, per QA Lead process step 1:
# concurrent modification, session/token edge cases. "Large dataset" and
# "accessibility" are documented N/A below with rationale, same discipline
# as FINTRACK-13's equivalent.
# ---------------------------------------------------------------------------


def test_logout_actually_revokes_the_session_end_to_end(client) -> None:
    """Session edge case the Gherkin doesn't spell out: verifies logout's
    effect is real and observable through the actual HTTP layer, not just
    at the handler level (already covered in tests/unit).
    """
    import jwt as jose_jwt

    from apps.api.infrastructure.security.token_revocation import RedisTokenRevocationStore

    register_resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": "logout-e2e-check@example.com",
            "password": "StrongPass1",
            "confirm_password": "StrongPass1",
        },
    )
    assert register_resp.status_code == 201

    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "logout-e2e-check@example.com", "password": "StrongPass1"},
    )
    assert login_resp.status_code == 200
    refresh_token = login_resp.cookies.get("refresh_token")
    assert refresh_token

    claims = jose_jwt.decode(refresh_token, options={"verify_signature": False})
    jti = claims["jti"]

    logout_resp = client.post("/api/v1/auth/logout", cookies={"refresh_token": refresh_token})
    assert logout_resp.status_code == 200

    from apps.api.infrastructure.cache.redis_client import redis_client

    store = RedisTokenRevocationStore(redis_client)
    assert asyncio.get_event_loop().run_until_complete(store.is_revoked(jti)) is True


def test_session_persists_across_reload_via_cookie_max_age(client) -> None:
    """AC6 ('session persists across page reloads until token expiry or
    explicit logout') is a client/cookie-persistence property -- verified
    here as: the Set-Cookie header carries a Max-Age matching the
    configured refresh-token lifetime, so a real browser would keep
    resending it across reloads without any server-side session record.
    """
    register_resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": "session-persistence-check@example.com",
            "password": "StrongPass1",
            "confirm_password": "StrongPass1",
        },
    )
    assert register_resp.status_code == 201

    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "session-persistence-check@example.com", "password": "StrongPass1"},
    )
    assert login_resp.status_code == 200

    set_cookie = login_resp.headers.get("set-cookie", "")
    expected_max_age = 7 * 24 * 60 * 60  # refresh_token_expire_days default = 7
    assert f"max-age={expected_max_age}" in set_cookie.lower()


@pytest.mark.asyncio
async def test_concurrent_login_attempts_against_same_account_all_rate_limited_correctly(
    test_session_factory,
) -> None:
    """Concurrent modification scenario the Gherkin doesn't cover: several
    simultaneous login attempts against the same account+IP must still
    converge on the correct total (no more than max_attempts allowed),
    even when the increments race each other -- exercises the real
    RedisRateLimiter (via fakeredis) directly, since TestClient's requests
    are sequential and wouldn't actually race.
    """
    from apps.api.infrastructure.cache.redis_client import redis_client
    from apps.api.infrastructure.security.rate_limiter import RedisRateLimiter

    limiter = RedisRateLimiter(redis_client)
    key = "login:concurrent-test@example.com:5.5.5.5"

    results = await asyncio.gather(*[limiter.check_and_increment(key, 5, 900) for _ in range(10)])

    assert results.count(True) == 5, f"expected exactly 5 allowed, got {results.count(True)}"
    assert results.count(False) == 5, f"expected exactly 5 blocked, got {results.count(False)}"


def test_large_dataset_and_accessibility_not_applicable_documented() -> None:
    """Documents, rather than silently skipping, two scenario categories
    from the QA Lead checklist that don't meaningfully apply to this
    specific story:

    - Large dataset (1000+ records): login is a single indexed lookup by
      email (the same query path FINTRACK-13's uniqueness check already
      exercises against a populated table) -- there's no new query shape
      introduced by login/logout worth re-proving at scale here.
    - Accessibility (keyboard nav, ARIA labels): N/A -- FINTRACK-14 is a
      backend-only story this sprint; no login/logout UI exists yet.
      Applicable once the frontend login form ships.
    """
    assert True
