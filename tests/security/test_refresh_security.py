"""QA Lead security suite for FINTRACK-60 (session persistence via silent
token refresh) -- AC5 and AC6, plus the no-enumeration and rate-limit
properties the endpoint inherits from /login.

API-level, same wiring as tests/security/test_login_security.py: real app,
real router, real JWT issuance, fakeredis for the denylist and rate
limiter (tests/conftest.py).

These assert the properties from
docs/threat-models/FINTRACK-60-session-persistence-threat-model.md that
are testable server-side: T1 (replay), T4 (token-type confusion), T5
(rate limit), T9 (cookie path scoping), T10 (post-logout replay), and the
F-02 no-token-in-body policy. T3's browser half and T7's cross-tab race
are not observable here and are named as gaps in the QA Lead envelope.
"""
from __future__ import annotations

import uuid

# PyJWT, under the legacy alias this repo already uses in
# tests/integration/test_login_logout_api.py -- python-jose was replaced by
# PyJWT under ADR-006, so there is no `jose` package to import.
import jwt as jose_jwt

from apps.api.infrastructure.security.token_service import TokenService

_TEST_SECRET = "test-secret-key-not-for-production-use-only"
_PASSWORD = "StrongPass1"


def _register(client):
    email = f"refresh-sec-{uuid.uuid4().hex[:8]}@example.com"
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "confirm_password": _PASSWORD},
    )
    assert resp.status_code == 201, resp.text
    return email, resp.cookies.get("refresh_token")


def _refresh(client, cookie):
    kwargs = {"cookies": {"refresh_token": cookie}} if cookie is not None else {}
    return client.post("/api/v1/auth/refresh", **kwargs)


# ---------------------------------------------------------------------------
# T1 / AC5 -- rotation makes a stolen token single-use
# ---------------------------------------------------------------------------


def test_a_stolen_refresh_token_works_once_and_then_never_again(client) -> None:
    """The honest shape of this control, asserted rather than glossed:
    rotation does NOT prevent the first fraudulent use. It guarantees the
    second is rejected -- which is what turns theft into a detectable
    event. The threat model records this as residual risk T1.
    """
    _, stolen = _register(client)

    first = _refresh(client, stolen)
    assert first.status_code == 200  # the thief's first use succeeds

    second = _refresh(client, stolen)
    assert second.status_code == 401  # every use after it does not


def test_replay_is_logged_at_warning_while_ordinary_expiry_is_not(client, caplog) -> None:
    """The level distinction is load-bearing: FINTRACK-64's alerting keys
    on WARNING. If a replay were logged at INFO alongside routine
    rejections, the signal would be indistinguishable from noise."""
    _, cookie = _register(client)
    _refresh(client, cookie)
    caplog.clear()

    _refresh(client, cookie)

    replay = [r for r in caplog.records if r.getMessage() == "refresh_replay_detected"]
    assert replay and all(r.levelname == "WARNING" for r in replay)

    caplog.clear()
    _refresh(client, "not-a-jwt")
    assert not [r for r in caplog.records if r.getMessage() == "refresh_replay_detected"]
    assert [r for r in caplog.records if r.getMessage() == "refresh_failed"]


def test_rotation_invalidates_the_old_token_even_for_a_different_client(client) -> None:
    """Revocation is server-side, so it holds regardless of which client
    presents the old token -- a thief on another machine is not a
    different case."""
    _, original = _register(client)
    rotated = _refresh(client, original).cookies.get("refresh_token")

    assert _refresh(client, original).status_code == 401
    assert _refresh(client, rotated).status_code == 200


# ---------------------------------------------------------------------------
# T10 -- logout's revocation finally has a reader
# ---------------------------------------------------------------------------


def test_a_logged_out_refresh_token_cannot_refresh(client) -> None:
    _, cookie = _register(client)
    assert client.post("/api/v1/auth/logout", cookies={"refresh_token": cookie}).status_code == 200

    assert _refresh(client, cookie).status_code == 401


# ---------------------------------------------------------------------------
# T4 -- token-type confusion
# ---------------------------------------------------------------------------


def test_an_access_token_cannot_be_presented_as_a_refresh_cookie(client) -> None:
    email = f"refresh-sec-{uuid.uuid4().hex[:8]}@example.com"
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "confirm_password": _PASSWORD},
    )
    access_token = reg.json()["access_token"]

    assert _refresh(client, access_token).status_code == 401


def test_a_foreign_signed_token_is_rejected(client) -> None:
    foreign = TokenService(secret_key="an-attacker-controlled-signing-secret-value")
    forged = foreign.issue_pair(uuid.uuid4()).refresh_token

    assert _refresh(client, forged).status_code == 401


# ---------------------------------------------------------------------------
# No enumeration -- every rejection looks identical to the caller
# ---------------------------------------------------------------------------


def test_every_rejection_reason_returns_an_identical_response(client) -> None:
    """Missing, malformed, expired, wrong-type and replayed must be
    indistinguishable from outside. A caller learning WHICH failed would
    learn whether a token was ever valid."""
    _, cookie = _register(client)
    _refresh(client, cookie)  # rotate, so `cookie` is now a replay

    expired = TokenService(secret_key=_TEST_SECRET, refresh_token_expire_days=-1)
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"enum-{uuid.uuid4().hex[:8]}@example.com",
            "password": _PASSWORD,
            "confirm_password": _PASSWORD,
        },
    )
    access_token = reg.json()["access_token"]

    # Five probes plus the rotating call above exceed the 5-per-15-minutes
    # budget /refresh shares with /login, so the last probe used to come
    # back 429 and this assertion read `{401, 429} == {401}`. The limit is
    # correct and is asserted deliberately by
    # test_refresh_is_rate_limited_on_the_same_budget_as_login -- it just
    # must not bleed into a test about response UNIFORMITY. Reset between
    # probes using the same mechanism conftest.py's autouse
    # _reset_rate_limiter fixture uses, so each probe is measured on its
    # own.
    from apps.api.presentation.api.v1.auth import limiter

    probes = [
        None,
        "not-a-jwt",
        expired.issue_pair(uuid.uuid4()).refresh_token,
        access_token,
        cookie,
    ]

    responses = []
    for probe in probes:
        limiter.reset()
        responses.append(_refresh(client, probe))

    assert {r.status_code for r in responses} == {401}
    assert {r.json()["detail"] for r in responses} == {"Session expired, please sign in again"}


# ---------------------------------------------------------------------------
# AC6 / F-02 -- nothing leaks into the body or into script-readable storage
# ---------------------------------------------------------------------------


def test_the_rotated_refresh_token_never_appears_in_the_response_body(client) -> None:
    _, cookie = _register(client)
    resp = _refresh(client, cookie)

    rotated = resp.cookies.get("refresh_token")
    assert rotated
    assert rotated not in resp.text
    assert "refresh_token" not in resp.json()


def test_the_refresh_cookie_carries_every_required_attribute(client) -> None:
    """Byte-for-byte the same attribute set as /register, /login and
    /oauth/* -- drift here means the cookie stops being replaced and starts
    being duplicated."""
    _, cookie = _register(client)
    set_cookie = _refresh(client, cookie).headers.get("set-cookie", "")

    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "samesite=strict" in set_cookie.lower()
    assert "path=/api/v1/auth" in set_cookie.lower()
    assert f"max-age={7 * 24 * 60 * 60}" in set_cookie.lower()


def test_the_response_never_sets_the_access_token_as_a_cookie(client) -> None:
    """AC6: the access token is in-memory only. If the server ever set it
    as a cookie it would be persisted by the browser regardless of what
    apps/web does."""
    _, cookie = _register(client)
    resp = _refresh(client, cookie)

    assert "access_token" not in resp.headers.get("set-cookie", "")


def test_no_token_value_is_ever_written_to_the_logs(client, caplog) -> None:
    _, cookie = _register(client)
    caplog.clear()
    resp = _refresh(client, cookie)

    rotated = resp.cookies.get("refresh_token")
    access = resp.json()["access_token"]
    logged = "\n".join(r.getMessage() + str(getattr(r, "context", "")) for r in caplog.records)
    assert cookie not in logged
    assert rotated not in logged
    assert access not in logged


def test_success_is_logged_with_user_id_only_and_no_email(client, caplog) -> None:
    email, cookie = _register(client)
    caplog.clear()
    _refresh(client, cookie)

    succeeded = [r for r in caplog.records if r.getMessage() == "refresh_succeeded"]
    assert succeeded
    assert email not in "\n".join(str(getattr(r, "context", "")) for r in succeeded)


# ---------------------------------------------------------------------------
# T5 -- rate limiting
# ---------------------------------------------------------------------------


def test_refresh_is_rate_limited_on_the_same_budget_as_login(client) -> None:
    """Unauthenticated, and each call does a Redis write plus a JWT sign --
    worth bounding. 5 per 15 minutes, matching /login."""
    from apps.api.config import get_settings

    limit = get_settings().login_rate_limit_attempts
    statuses = [_refresh(client, "not-a-jwt").status_code for _ in range(limit + 2)]

    assert 429 in statuses, f"expected a 429 within {limit + 2} attempts, got {statuses}"


# ---------------------------------------------------------------------------
# T9 -- cookie path scoping
# ---------------------------------------------------------------------------


def test_the_refresh_cookie_is_scoped_away_from_business_endpoints(client) -> None:
    """path=/api/v1/auth keeps the credential off every transactions,
    budgets and alerts request -- it is only ever sent where it is needed."""
    _, cookie = _register(client)
    set_cookie = _refresh(client, cookie).headers.get("set-cookie", "").lower()

    assert "path=/api/v1/auth" in set_cookie


def test_the_rotated_token_belongs_to_the_same_user(client) -> None:
    _, cookie = _register(client)
    resp = _refresh(client, cookie)

    old_sub = jose_jwt.decode(cookie, options={"verify_signature": False})["sub"]
    new_sub = jose_jwt.decode(
        resp.cookies.get("refresh_token"), options={"verify_signature": False}
    )["sub"]
    assert old_sub == new_sub == resp.json()["user_id"]
