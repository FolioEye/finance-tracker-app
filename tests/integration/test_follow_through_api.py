"""QA Lead integration suite for FINTRACK-23 (Action Follow-Through
Tracking). Same approach as tests/integration/test_recommendations_api.py:
hits the real FastAPI app over HTTP via TestClient, backed by a genuine
SQLite DB and fakeredis (see tests/conftest.py).

Every scenario in
tests/features/FINTRACK-23-action-follow-through-tracking.feature maps to
a test function below, plus non-Gherkin additions the skill requires
(concurrent-modification/idempotency, large dataset, session edge case).

AC4's 7-day auto-ignore boundary already has full pinned-clock coverage
at the unit level (test_follow_through_handlers.py). At this level,
GET /recommendations/weekly always uses real wall-clock date.today() for
period_start (correct production behaviour -- a recommendation really is
"shown today"), so there's no dependency-override seam to pin a fake
clock through the API the way test_alerts_api.py's monthly-boundary test
does. Instead, the "8 days ago" scenario seeds a FollowThroughRecordModel
row directly via the test DB session (test_session_factory) with an old
period_start, then exercises the real GET endpoints to prove read-time
reconciliation picks it up -- a standard arrange-via-DB/act-via-API split,
not a workaround for a defect.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest


def _register_and_login(client, email: str, password: str = "StrongPass1") -> str:
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "confirm_password": password},
    )
    assert resp.status_code == 201, resp.text
    login_resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login_resp.status_code == 200, login_resp.text
    return login_resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _get_recommendation(client, token: str):
    return client.get("/api/v1/recommendations/weekly", headers=_auth(token))


def _record_action(client, token: str, record_id: str, action: str):
    return client.post(
        f"/api/v1/follow-through/{record_id}/actions", json={"action": action}, headers=_auth(token)
    )


def _history(client, token: str):
    return client.get("/api/v1/follow-through", headers=_auth(token))


def _rate(client, token: str):
    return client.get("/api/v1/follow-through/rate", headers=_auth(token))


async def _seed_record(test_session_factory, user_id, period_start, status, recommendation_type="BUDGET_RISK"):
    """Direct DB seed for period_start values the real API can't produce
    (anything other than today) -- see module docstring."""
    import uuid as uuid_mod
    from datetime import datetime, timezone

    from apps.api.infrastructure.database.models import FollowThroughRecordModel

    record_id = uuid_mod.uuid4()
    async with test_session_factory() as session:
        session.add(
            FollowThroughRecordModel(
                id=record_id,
                user_id=uuid_mod.UUID(user_id),
                period_start=period_start,
                recommendation_type=recommendation_type,
                status=status,
                created_at=datetime.now(timezone.utc),
                actioned_at=None,
            )
        )
        await session.commit()
    return str(record_id)


def _user_id_from_token(client, token: str) -> str:
    # There's no /me endpoint -- infer the user_id via a follow-through
    # record already created for this token (recommendation GET always
    # creates one), same technique other integration suites use to avoid
    # decoding the JWT directly in a test.
    resp = _get_recommendation(client, token)
    assert resp.status_code == 200
    return resp.json()["follow_through_record_id"]


# ---------------------------------------------------------------------------
# Scenario: User marks a recommendation as done
# ---------------------------------------------------------------------------


def test_user_marks_a_recommendation_as_done(client) -> None:
    token = _register_and_login(client, "ft23-mark-done@example.com")
    rec = _get_recommendation(client, token)
    assert rec.status_code == 200
    record_id = rec.json()["follow_through_record_id"]
    assert record_id is not None

    action_resp = _record_action(client, token, record_id, "done")
    assert action_resp.status_code == 204

    history = _history(client, token).json()["items"]
    assert history[0]["status"] == "DONE"
    assert history[0]["actioned_at"] is not None


# ---------------------------------------------------------------------------
# Scenario: User dismisses a recommendation
# ---------------------------------------------------------------------------


def test_user_dismisses_a_recommendation_and_it_still_counts_toward_the_denominator(client) -> None:
    token = _register_and_login(client, "ft23-dismiss@example.com")
    rec = _get_recommendation(client, token)
    record_id = rec.json()["follow_through_record_id"]

    action_resp = _record_action(client, token, record_id, "dismiss")
    assert action_resp.status_code == 204

    history = _history(client, token).json()["items"]
    assert history[0]["status"] == "DISMISSED"

    rate = _rate(client, token).json()
    assert rate["dismissed_count"] == 1
    assert rate["done_count"] == 0
    assert rate["rate_pct"] == "0.00"  # dismissed counts in denominator, not numerator


# ---------------------------------------------------------------------------
# Scenario: Recommendation goes unactioned past the review window
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommendation_unactioned_past_seven_days_is_auto_ignored(client, test_session_factory) -> None:
    token = _register_and_login(client, "ft23-auto-ignore@example.com")
    user_id = _user_id_from_token(client, token)
    # get_current_user_id resolves from the JWT `sub` claim -- decode it
    # here purely to seed a row under the same user, not to bypass auth.
    import jwt as pyjwt

    from apps.api.config import get_settings

    settings = get_settings()
    decoded = pyjwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    real_user_id = decoded["sub"]

    old_period = date.today() - timedelta(days=8)
    await _seed_record(test_session_factory, real_user_id, old_period, "PENDING")

    history = _history(client, token).json()["items"]
    stale = [r for r in history if r["period_start"] == old_period.isoformat()]
    assert len(stale) == 1
    assert stale[0]["status"] == "IGNORED"


# ---------------------------------------------------------------------------
# Scenario: Follow-through records are scoped to the authenticated user only
# ---------------------------------------------------------------------------


def test_follow_through_history_scoped_to_the_authenticated_user_only(client) -> None:
    token_a = _register_and_login(client, "ft23-scope-a@example.com")
    token_b = _register_and_login(client, "ft23-scope-b@example.com")

    _get_recommendation(client, token_a)
    _get_recommendation(client, token_b)

    history_b = _history(client, token_b).json()["items"]
    assert len(history_b) == 1  # only user B's own record, never user A's


# ---------------------------------------------------------------------------
# Scenario: Attempt to submit an invalid action value
# ---------------------------------------------------------------------------


def test_invalid_action_value_is_rejected_with_no_state_change(client) -> None:
    token = _register_and_login(client, "ft23-invalid-action@example.com")
    rec = _get_recommendation(client, token)
    record_id = rec.json()["follow_through_record_id"]

    resp = _record_action(client, token, record_id, "delete")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid action value"

    history = _history(client, token).json()["items"]
    assert history[0]["status"] == "PENDING"  # untouched


# ---------------------------------------------------------------------------
# Scenario: Attempt to mark another user's recommendation as done (IDOR)
# ---------------------------------------------------------------------------


def test_cannot_mark_another_users_recommendation_record_as_done(client) -> None:
    victim_token = _register_and_login(client, "ft23-idor-victim@example.com")
    attacker_token = _register_and_login(client, "ft23-idor-attacker@example.com")

    victim_rec = _get_recommendation(client, victim_token)
    victim_record_id = victim_rec.json()["follow_through_record_id"]

    resp = _record_action(client, attacker_token, victim_record_id, "done")
    assert resp.status_code == 404  # not 403 -- can't confirm the id exists

    victim_history = _history(client, victim_token).json()["items"]
    assert victim_history[0]["status"] == "PENDING"  # untouched


# ---------------------------------------------------------------------------
# Scenario: Follow-Through Rate reflects a mix of done/dismissed/ignored
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_follow_through_rate_reflects_a_mix_of_done_dismissed_and_ignored(client, test_session_factory) -> None:
    token = _register_and_login(client, "ft23-rate-mix@example.com")
    import jwt as pyjwt

    from apps.api.config import get_settings

    settings = get_settings()
    decoded = pyjwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    real_user_id = decoded["sub"]

    # 1 done via the real API (today)
    rec = _get_recommendation(client, token)
    record_id = rec.json()["follow_through_record_id"]
    _record_action(client, token, record_id, "done")

    # 1 more done, 1 dismissed, 1 ignored -- seeded directly on distinct
    # past days so they don't collide with today's unique (user, period) row
    await _seed_record(test_session_factory, real_user_id, date.today() - timedelta(days=1), "DONE")
    await _seed_record(test_session_factory, real_user_id, date.today() - timedelta(days=2), "DISMISSED")
    await _seed_record(test_session_factory, real_user_id, date.today() - timedelta(days=3), "IGNORED")

    rate = _rate(client, token).json()
    assert rate["done_count"] == 2
    assert rate["dismissed_count"] == 1
    assert rate["ignored_count"] == 1
    assert rate["rate_pct"] == "50.00"


# ---------------------------------------------------------------------------
# Non-Gherkin additions (per fintrack-qa-lead skill process item 1)
# ---------------------------------------------------------------------------


def test_concurrent_refresh_same_day_reuses_the_same_record_idempotently(client) -> None:
    """Simulates a user hitting refresh twice in quick succession -- both
    calls must resolve to the same follow_through_record_id, never a
    second row for the same day."""
    token = _register_and_login(client, "ft23-concurrent-refresh@example.com")

    first = _get_recommendation(client, token).json()["follow_through_record_id"]
    second = _get_recommendation(client, token).json()["follow_through_record_id"]

    assert first == second
    history = _history(client, token).json()["items"]
    assert len(history) == 1


@pytest.mark.asyncio
async def test_large_history_still_returns_correctly_and_rate_only_counts_the_rolling_window(
    client, test_session_factory
) -> None:
    """Large-dataset check: 90 days of history (well past the 56-day rate
    window) -- history returns all of it, rate only counts what's inside
    the window."""
    token = _register_and_login(client, "ft23-large-dataset@example.com")
    import jwt as pyjwt

    from apps.api.config import get_settings

    settings = get_settings()
    decoded = pyjwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    real_user_id = decoded["sub"]

    for days_ago in range(1, 91):
        await _seed_record(test_session_factory, real_user_id, date.today() - timedelta(days=days_ago), "DONE")

    history = _history(client, token).json()["items"]
    assert len(history) == 90

    rate = _rate(client, token).json()
    assert rate["done_count"] == 55  # window_start = today - 55 days; days_ago 1..55 fall inside it


def test_session_edge_case_expired_token_rejected_on_history(client) -> None:
    import jwt as pyjwt

    from apps.api.config import get_settings

    settings = get_settings()
    expired = pyjwt.encode(
        {"sub": "00000000-0000-0000-0000-000000000000", "type": "access", "jti": "x", "exp": 1},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    resp = client.get("/api/v1/follow-through", headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401
