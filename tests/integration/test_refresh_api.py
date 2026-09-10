"""QA Lead integration suite for FINTRACK-60 (session persistence via
silent token refresh).

Same approach as tests/integration/test_login_logout_api.py: hits the real
FastAPI app over HTTP via TestClient, backed by a genuine SQLite DB and a
genuine fakeredis instance for rate limiting and token revocation -- see
tests/conftest.py.

Every scenario below maps 1:1 to a scenario in
tests/features/FINTRACK-60-session-persistence-silent-refresh.feature. No
Gherkin step text was altered to make it pass -- pytest-bdd fails at
collection time if a step in that file has no matching implementation
here. Until this module existed the feature file was committed but
UNBOUND, so it silently contributed nothing to CI; binding it is the point
of this file.

SCOPE NOTE, stated plainly rather than buried: several Gherkin steps
describe browser behaviour (ProtectedRoute ordering, localStorage,
document.cookie, redirect counts). An API-level test cannot observe a
browser. Each such step is implemented here as an assertion on the API
contract that *makes* the browser behaviour possible -- e.g. "not readable
via document.cookie" is verified as "the Set-Cookie carries HttpOnly",
which is the server-side property the browser rule derives from. This
mirrors how FINTRACK-14 handled "session persists across reload", where
the cookie's max-age was asserted rather than a real reload. The genuinely
browser-side assertions belong in the Playwright suite and are listed as a
coverage gap in the QA Lead envelope -- they are NOT claimed as covered
here.
"""
from __future__ import annotations

import uuid

import pytest
from jose import jwt as jose_jwt
from pytest_bdd import given, parsers, scenarios, then, when

from apps.api.infrastructure.security.token_service import TokenService

scenarios("../features/FINTRACK-60-session-persistence-silent-refresh.feature")

_TEST_SECRET = "test-secret-key-not-for-production-use-only"
_PASSWORD = "StrongPass1"


class RefreshContext:
    """Per-scenario mutable state shared between Given/When/Then steps."""

    def __init__(self) -> None:
        self.email = None
        self.user_id = None
        self.original_cookie = None
        self.response = None
        self.replay_response = None
        self.requested_path = None


@pytest.fixture
def ctx() -> RefreshContext:
    return RefreshContext()


def _register(client, ctx: RefreshContext):
    """Register a fresh user and capture the refresh cookie the API sets."""
    ctx.email = f"refresh-{uuid.uuid4().hex[:8]}@example.com"
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": ctx.email, "password": _PASSWORD, "confirm_password": _PASSWORD},
    )
    assert resp.status_code == 201, resp.text
    ctx.user_id = resp.json()["user_id"]
    ctx.original_cookie = resp.cookies.get("refresh_token")
    assert ctx.original_cookie, "register should set a refresh_token cookie"
    return resp


def _refresh(client, cookie):
    """POST /refresh with an explicit cookie.

    Cookies are passed explicitly rather than relying on the TestClient's
    jar: the cookie is issued Secure, and a cookie jar is entitled to
    withhold a Secure cookie from the http://testserver base URL. Passing
    it explicitly tests the endpoint's own behaviour without depending on
    client-side jar policy -- the same pattern test_login_logout_api.py
    uses for logout.
    """
    kwargs = {"cookies": {"refresh_token": cookie}} if cookie is not None else {}
    return client.post("/api/v1/auth/refresh", **kwargs)


# ---------------------------------------------------------------------------
# Background
# ---------------------------------------------------------------------------


@given("the API exposes POST /api/v1/auth/refresh")
def api_exposes_refresh(client) -> None:
    # Assert the route is actually registered rather than assuming it. A
    # missing route would otherwise surface as a 404 mid-scenario and read
    # like a logic failure instead of a wiring one.
    from apps.api.main import app

    paths = {r.path for r in app.routes if hasattr(r, "methods") and "POST" in r.methods}
    assert "/api/v1/auth/refresh" in paths


@given("the access token is held in memory only with a 15 minute lifetime")
def access_token_lifetime() -> None:
    from apps.api.config import get_settings

    assert get_settings().access_token_expire_minutes == 15


@given("a successful login sets a 7-day httpOnly refresh_token cookie")
def login_sets_refresh_cookie() -> None:
    from apps.api.config import get_settings

    assert get_settings().refresh_token_expire_days == 7


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given("I signed in successfully and hold a valid refresh_token cookie")
def signed_in_with_valid_cookie(client, ctx: RefreshContext) -> None:
    _register(client, ctx)


@given("my in-memory access token has been discarded by the page reload")
def access_token_discarded(ctx: RefreshContext) -> None:
    # The access token living in memory only is precisely why a reload
    # loses it -- there is no server-side state to clear. Modelled by never
    # sending an Authorization header on the refresh call, which every step
    # below already does.
    assert ctx.original_cookie is not None


@given("my refresh_token cookie has passed its 7-day expiry")
def expired_refresh_cookie(client, ctx: RefreshContext) -> None:
    _register(client, ctx)
    # Mint a genuinely expired refresh token with the real TokenService
    # rather than hand-crafting a JWT: this exercises the real decode path
    # and its ExpiredTokenError, which is what the handler branches on.
    expired_service = TokenService(secret_key=_TEST_SECRET, refresh_token_expire_days=-1)
    ctx.original_cookie = expired_service.issue_pair(uuid.UUID(ctx.user_id)).refresh_token


@given("I have never signed in and hold no refresh_token cookie")
def no_cookie_at_all(ctx: RefreshContext) -> None:
    ctx.original_cookie = None


@given(parsers.parse('I hold a valid refresh_token cookie with value "{label}"'))
def hold_cookie_labelled(client, ctx: RefreshContext, label: str) -> None:
    # The Gherkin names the token "OLD_REFRESH_TOKEN" as a label for the
    # value held BEFORE rotation, not as a literal token string -- a
    # literal would not verify, so the scenario would pass for the wrong
    # reason (rejected as malformed rather than as a replay).
    _register(client, ctx)


@given("I have completed a successful silent refresh")
def completed_successful_refresh(client, ctx: RefreshContext) -> None:
    _register(client, ctx)
    ctx.response = _refresh(client, ctx.original_cookie)
    assert ctx.response.status_code == 200, ctx.response.text


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when("I refresh the browser on /dashboard")
def refresh_browser_on_dashboard(client, ctx: RefreshContext) -> None:
    ctx.requested_path = "/dashboard"
    ctx.response = _refresh(client, ctx.original_cookie)


@when("I open the application at /dashboard")
def open_application_at_dashboard(client, ctx: RefreshContext) -> None:
    ctx.requested_path = "/dashboard"
    ctx.response = _refresh(client, ctx.original_cookie)


@when("I navigate directly to /transactions?month=2026-09")
def navigate_to_deep_link(client, ctx: RefreshContext) -> None:
    ctx.requested_path = "/transactions?month=2026-09"
    ctx.response = _refresh(client, ctx.original_cookie)


@when("POST /api/v1/auth/refresh succeeds and rotates the cookie")
def refresh_succeeds_and_rotates(client, ctx: RefreshContext) -> None:
    ctx.response = _refresh(client, ctx.original_cookie)
    assert ctx.response.status_code == 200, ctx.response.text
    rotated = ctx.response.cookies.get("refresh_token")
    assert rotated and rotated != ctx.original_cookie


@when(parsers.parse('a request is replayed to POST /api/v1/auth/refresh presenting "{label}"'))
def replay_old_token(client, ctx: RefreshContext, label: str) -> None:
    # Deliberately re-presents the ORIGINAL cookie, which the previous step
    # rotated away -- that is what makes this a replay rather than a
    # malformed-token case.
    ctx.replay_response = _refresh(client, ctx.original_cookie)


@when("I inspect the browser storage and the refresh response body")
def inspect_storage_and_body(ctx: RefreshContext) -> None:
    # No browser here; the assertions in this scenario's Then steps read
    # the response the browser would have received. See the SCOPE NOTE.
    assert ctx.response is not None


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then(
    "the web app should call POST /api/v1/auth/refresh before ProtectedRoute evaluates my session"
)
def refresh_called_before_route_evaluation(ctx: RefreshContext) -> None:
    # Ordering inside the SPA is a frontend concern (authStore.bootstrapState
    # gates ProtectedRoute). What this suite can assert is the server-side
    # precondition: the call succeeds with only the cookie and no
    # Authorization header -- which is what lets it run before any session
    # exists in memory.
    assert ctx.response.status_code == 200
    assert "authorization" not in {k.lower() for k in ctx.response.request.headers}


@then("the response should return a new 15 minute access token")
def returns_new_access_token(ctx: RefreshContext) -> None:
    body = ctx.response.json()
    assert body["expires_in"] == 15 * 60
    assert body["token_type"] == "bearer"
    claims = jose_jwt.decode(body["access_token"], options={"verify_signature": False})
    assert claims["type"] == "access"


@then("the refresh_token cookie should be rotated to a new value")
def cookie_rotated(ctx: RefreshContext) -> None:
    rotated = ctx.response.cookies.get("refresh_token")
    assert rotated, "refresh should set a new refresh_token cookie"
    assert rotated != ctx.original_cookie, "refresh must rotate, not reissue the same token"
    old = jose_jwt.decode(ctx.original_cookie, options={"verify_signature": False})
    new = jose_jwt.decode(rotated, options={"verify_signature": False})
    assert old["jti"] != new["jti"], "rotation must mint a fresh jti, not just re-sign"
    assert old["sub"] == new["sub"], "rotation must preserve the subject"


@then("I should land on /dashboard still authenticated")
def land_on_dashboard_authenticated(ctx: RefreshContext) -> None:
    assert ctx.requested_path == "/dashboard"
    assert ctx.response.status_code == 200
    assert ctx.response.json()["user_id"] == ctx.user_id


@then("I should never see the /login screen, not even momentarily")
def never_see_login(ctx: RefreshContext) -> None:
    # Server-side equivalent: the refresh resolves authoritatively in one
    # call with no redirect, so the SPA never has an intermediate
    # unauthenticated state to render.
    assert ctx.response.status_code == 200
    assert not ctx.response.history, "refresh must not redirect"


@then("POST /api/v1/auth/refresh should respond 401 Unauthorized")
def responds_401(ctx: RefreshContext) -> None:
    assert ctx.response.status_code == 401


@then("no new access token should be issued")
def no_access_token_issued(ctx: RefreshContext) -> None:
    assert "access_token" not in ctx.response.json()


@then("no new refresh_token cookie should be set")
def no_new_cookie_set(ctx: RefreshContext) -> None:
    assert "refresh_token" not in ctx.response.headers.get("set-cookie", "")


@then("I should be redirected to /login exactly once with no redirect loop")
def redirected_to_login_once(ctx: RefreshContext) -> None:
    # A 401 is terminal: the API neither redirects nor retries, so the SPA
    # gets one unambiguous answer and routes to /login a single time. A
    # server-side redirect here is what would create a loop.
    assert ctx.response.status_code == 401
    assert not ctx.response.history


@then("the silent refresh attempt should fail fast without throwing an unhandled error")
def fails_fast_cleanly(ctx: RefreshContext) -> None:
    # A 500 would mean the missing-cookie path raised instead of being
    # handled -- the exact failure mode that would break first-time visitors.
    assert ctx.response.status_code == 401
    assert ctx.response.json()["detail"] == "Session expired, please sign in again"


@then("I should be redirected to /login")
def redirected_to_login(ctx: RefreshContext) -> None:
    assert ctx.response.status_code == 401


@then("the login screen should render normally rather than an error boundary")
def login_renders_normally(ctx: RefreshContext) -> None:
    # Server-side equivalent: the failure is a clean, structured 401 with a
    # JSON body -- not a 5xx or an HTML error page, either of which is what
    # would trip an error boundary in the SPA.
    assert ctx.response.status_code == 401
    assert ctx.response.headers["content-type"].startswith("application/json")


@then("the silent refresh should complete before any redirect decision is made")
def refresh_completes_before_redirect(ctx: RefreshContext) -> None:
    assert ctx.response.status_code == 200


@then("I should land on /transactions?month=2026-09 with the month filter intact")
def land_on_deep_link(ctx: RefreshContext) -> None:
    # The API is path-agnostic by design -- it authenticates, it does not
    # route. Preserving the deep link is therefore guaranteed by the API
    # NOT redirecting; React Router holds the location while the refresh
    # resolves.
    assert ctx.requested_path == "/transactions?month=2026-09"
    assert ctx.response.status_code == 200
    assert not ctx.response.history


@then("I should not be bounced to /dashboard or /login")
def not_bounced(ctx: RefreshContext) -> None:
    assert not ctx.response.history
    assert "location" not in {k.lower() for k in ctx.response.headers}


@then("the replayed request should be rejected with 401 Unauthorized")
def replay_rejected(ctx: RefreshContext) -> None:
    assert ctx.replay_response.status_code == 401


@then("no access token should be issued for the replayed request")
def no_token_for_replay(ctx: RefreshContext) -> None:
    assert "access_token" not in ctx.replay_response.json()
    assert "refresh_token" not in ctx.replay_response.headers.get("set-cookie", "")


@then("a security event should be logged recording the reuse attempt")
def security_event_logged(caplog) -> None:
    # refresh_replay_detected is deliberately WARNING while an ordinary
    # rejection is INFO -- a replay is a detection signal, not routine
    # expiry. Asserting the level as well as the event guards that
    # distinction, which FINTRACK-64's alerting will key on.
    replay_records = [r for r in caplog.records if r.getMessage() == "refresh_replay_detected"]
    assert replay_records, "a replayed refresh token must log refresh_replay_detected"
    assert all(r.levelname == "WARNING" for r in replay_records)


@then("the access token should not be present in localStorage or sessionStorage")
def access_token_not_in_storage(ctx: RefreshContext) -> None:
    # Browser storage is not observable here. The server-side guarantee is
    # that the API never instructs the client to persist it: the access
    # token is returned in the body for in-memory use and is never set as a
    # cookie, so nothing the server sends can end up in storage on its own.
    # Whether apps/web writes it to storage is a frontend assertion -- see
    # the SCOPE NOTE.
    assert "access_token" not in ctx.response.headers.get("set-cookie", "")


@then("the refresh_token cookie should not be readable via document.cookie")
def refresh_cookie_not_script_readable(ctx: RefreshContext) -> None:
    # HttpOnly is exactly the server-side property that makes
    # document.cookie unable to read it.
    assert "HttpOnly" in ctx.response.headers.get("set-cookie", "")


@then("the refresh_token cookie should carry the HttpOnly, Secure and SameSite attributes")
def cookie_carries_security_attributes(ctx: RefreshContext) -> None:
    set_cookie = ctx.response.headers.get("set-cookie", "")
    assert "refresh_token=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "samesite=strict" in set_cookie.lower()
    assert "path=/api/v1/auth" in set_cookie.lower()


@then("the refresh token value should not appear anywhere in the response body")
def refresh_token_absent_from_body(ctx: RefreshContext) -> None:
    # F-02: the rotated refresh token is cookie-only. Checking the raw text
    # rather than a parsed key catches it appearing under any field name.
    rotated = ctx.response.cookies.get("refresh_token")
    assert rotated
    assert rotated not in ctx.response.text
    assert "refresh_token" not in ctx.response.json()
