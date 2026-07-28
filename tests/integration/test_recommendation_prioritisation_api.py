"""QA Lead integration suite for FINTRACK-27 (Recommendation
Prioritisation from Follow-Through Outcomes). Same approach as
tests/integration/test_recommendations_api.py and
tests/integration/test_follow_through_api.py: hits the real FastAPI app
over HTTP via TestClient, backed by a genuine SQLite DB and fakeredis
(see tests/conftest.py).

Every scenario in
tests/features/FINTRACK-27-recommendation-prioritisation.feature that
concerns the *handler's* behavior (AC1-AC4, the two edge cases) maps to a
test function below. AC5 (per-user isolation) is this story's mandatory
security scenario per BA's own note and lives in
tests/security/test_recommendation_prioritisation_security.py instead,
matching how test_recommendations_api.py/test_recommendations_security.py
already split functional vs. security coverage for the same endpoint.

follow_through_records has a UNIQUE(user_id, period_start) constraint --
at most one row per user per calendar day, regardless of type/key -- so
seeding N occurrences of one (type, key) pair for a user requires N
distinct past period_start days, never the same day twice.
"""
from __future__ import annotations

import uuid as uuid_mod
from datetime import date, datetime, timedelta, timezone

import jwt as pyjwt
import pytest

from apps.api.config import get_settings


def _register_and_login(client, email: str, password: str = "StrongPass1") -> str:
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "confirm_password": password},
    )
    assert resp.status_code == 201, resp.text
    login_resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login_resp.status_code == 200, login_resp.text
    return login_resp.json()["access_token"]


def _decode_user_id(token: str) -> str:
    settings = get_settings()
    decoded = pyjwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    return decoded["sub"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _create_budget(client, token: str, category: str, monthly_limit: str):
    return client.post(
        "/api/v1/budgets",
        json={"category": category, "monthly_limit": monthly_limit},
        headers=_auth(token),
    )


def _create_transaction(client, token: str, amount: str, category: str, transaction_date: str):
    return client.post(
        "/api/v1/transactions",
        json={"amount": amount, "category": category, "transaction_date": transaction_date},
        headers=_auth(token),
    )


def _recommendation(client, token: str):
    return client.get("/api/v1/recommendations/weekly", headers=_auth(token))


async def _seed_follow_through(
    test_session_factory,
    user_id: str,
    period_start: date,
    status: str,
    recommendation_type: str,
    recommendation_key: str | None,
) -> None:
    from apps.api.infrastructure.database.models import FollowThroughRecordModel

    async with test_session_factory() as session:
        session.add(
            FollowThroughRecordModel(
                id=uuid_mod.uuid4(),
                user_id=uuid_mod.UUID(user_id),
                period_start=period_start,
                recommendation_type=recommendation_type,
                recommendation_key=recommendation_key,
                status=status,
                created_at=datetime.now(timezone.utc),
                actioned_at=None,
            )
        )
        await session.commit()


async def _seed_history(
    test_session_factory,
    user_id: str,
    recommendation_type: str,
    recommendation_key: str,
    statuses_oldest_first: list[str],
    days_ago_start: int = 20,
) -> None:
    """Seeds one row per status, on distinct past days (oldest first ->
    furthest in the past), so the most-recent-first ordering the
    repository relies on matches the order these tests reason about.
    days_ago_start should be large enough that different history blocks
    seeded in the same test never collide on period_start.
    """
    for i, status in enumerate(statuses_oldest_first):
        days_ago = days_ago_start - i
        await _seed_follow_through(
            test_session_factory,
            user_id,
            date.today() - timedelta(days=days_ago),
            status,
            recommendation_type,
            recommendation_key,
        )


# ---------------------------------------------------------------------------
# AC1: mostly-ignored budget category is passed over for a well-followed one
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deprioritised_budget_category_passed_over_via_real_api(client, test_session_factory) -> None:
    token = _register_and_login(client, "reco-prior-ac1@example.com")
    user_id = _decode_user_id(token)

    # Groceries would naturally win (95% used > Dining's 85%), but
    # Groceries has been mostly ignored -- Dining should be shown instead.
    assert _create_budget(client, token, "Dining", "100.00").status_code == 201
    assert _create_budget(client, token, "Groceries", "100.00").status_code == 201
    assert _create_transaction(client, token, "85.00", "Dining", "2026-07-05").status_code == 201
    assert _create_transaction(client, token, "95.00", "Groceries", "2026-07-05").status_code == 201

    # 2 done (long ago) + 8 ignored (most recent) -- 20% overall, and the
    # most-recent occurrence is NOT done, so no instant-recovery kicks in.
    await _seed_history(
        test_session_factory, user_id, "BUDGET_RISK", "Groceries",
        ["DONE"] * 2 + ["IGNORED"] * 8, days_ago_start=20,
    )
    await _seed_history(
        test_session_factory, user_id, "BUDGET_RISK", "Dining",
        ["DONE"] * 8 + ["DISMISSED"] * 2, days_ago_start=40,
    )

    resp = _recommendation(client, token)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["type"] == "BUDGET_RISK"
    assert body["category"] == "Dining"
    assert body["deprioritization_reason"] is not None
    assert "Groceries" in body["deprioritization_reason"]


@pytest.mark.asyncio
async def test_well_followed_budget_category_keeps_native_priority_via_real_api(
    client, test_session_factory
) -> None:
    token = _register_and_login(client, "reco-prior-ac1-happy@example.com")
    user_id = _decode_user_id(token)

    assert _create_budget(client, token, "Dining", "100.00").status_code == 201
    assert _create_budget(client, token, "Groceries", "100.00").status_code == 201
    assert _create_transaction(client, token, "85.00", "Dining", "2026-07-05").status_code == 201
    assert _create_transaction(client, token, "95.00", "Groceries", "2026-07-05").status_code == 201

    await _seed_history(
        test_session_factory, user_id, "BUDGET_RISK", "Groceries",
        ["DONE"] * 8 + ["DISMISSED"] * 2, days_ago_start=20,
    )
    await _seed_history(
        test_session_factory, user_id, "BUDGET_RISK", "Dining",
        ["DONE"] * 8 + ["DISMISSED"] * 2, days_ago_start=40,
    )

    resp = _recommendation(client, token)
    body = resp.json()
    assert body["category"] == "Groceries"  # native order (highest percent-used) unchanged
    assert body["deprioritization_reason"] is None


# ---------------------------------------------------------------------------
# AC2: instant recovery the moment the most recent occurrence is DONE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recovered_budget_category_wins_back_native_priority(client, test_session_factory) -> None:
    """Dining has a low overall rate (2 of 10 done, 20%) but its single
    MOST RECENT occurrence was DONE -- BA's recovery rule says this must
    already be back to normal, so as the native top pick (90% used) it
    should win over Groceries (85% used, never deprioritised).
    """
    token = _register_and_login(client, "reco-prior-ac2-recovery@example.com")
    user_id = _decode_user_id(token)

    assert _create_budget(client, token, "Dining", "100.00").status_code == 201
    assert _create_budget(client, token, "Groceries", "100.00").status_code == 201
    assert _create_transaction(client, token, "90.00", "Dining", "2026-07-05").status_code == 201
    assert _create_transaction(client, token, "85.00", "Groceries", "2026-07-05").status_code == 201

    # 8 ignored, 1 done, then the MOST RECENT one done (2 of 10 overall --
    # would fail the 30% rate check on its own, but recovery overrides it).
    await _seed_history(
        test_session_factory, user_id, "BUDGET_RISK", "Dining",
        ["IGNORED"] * 8 + ["DONE", "DONE"], days_ago_start=20,
    )
    await _seed_history(
        test_session_factory, user_id, "BUDGET_RISK", "Groceries",
        ["DONE"] * 8 + ["DISMISSED"] * 2, days_ago_start=40,
    )

    resp = _recommendation(client, token)
    body = resp.json()
    assert body["category"] == "Dining"  # recovered, back to native top pick
    assert body["deprioritization_reason"] is None


# ---------------------------------------------------------------------------
# AC4: never reorders across FINTRACK-21's existing trigger tiers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deprioritised_budget_risk_still_outranks_normal_subscription_via_real_api(
    client, test_session_factory
) -> None:
    token = _register_and_login(client, "reco-prior-ac4@example.com")
    user_id = _decode_user_id(token)

    assert _create_budget(client, token, "Dining", "100.00").status_code == 201
    assert _create_transaction(client, token, "90.00", "Dining", "2026-07-05").status_code == 201
    hulu_resp = _create_transaction(client, token, "9.99", "Entertainment", "2026-06-20")
    assert hulu_resp.status_code == 201

    await _seed_history(
        test_session_factory, user_id, "BUDGET_RISK", "Dining",
        ["DONE"] * 2 + ["IGNORED"] * 8, days_ago_start=20,
    )

    resp = _recommendation(client, token)
    body = resp.json()
    # BUDGET_RISK still wins regardless of its own low follow-through --
    # AC4's tier ordering is never affected by follow-through.
    assert body["type"] == "BUDGET_RISK"
    assert body["category"] == "Dining"


# ---------------------------------------------------------------------------
# Edge case: too few occurrences -- minimum sample size not reached
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_category_with_too_few_occurrences_keeps_native_priority(
    client, test_session_factory
) -> None:
    token = _register_and_login(client, "reco-prior-min-sample@example.com")
    user_id = _decode_user_id(token)

    assert _create_budget(client, token, "Dining", "100.00").status_code == 201
    assert _create_transaction(client, token, "85.00", "Dining", "2026-07-05").status_code == 201

    # Only 2 occurrences, both ignored (0%) -- below MIN_SAMPLE=3, so must
    # NOT be deprioritised despite the rate looking terrible.
    await _seed_history(
        test_session_factory, user_id, "BUDGET_RISK", "Dining", ["IGNORED", "IGNORED"], days_ago_start=20,
    )

    resp = _recommendation(client, token)
    body = resp.json()
    assert body["type"] == "BUDGET_RISK"
    assert body["category"] == "Dining"
    assert body["deprioritization_reason"] is None


# ---------------------------------------------------------------------------
# Negative/edge case: brand-new category with no follow-through history
# ---------------------------------------------------------------------------


def test_brand_new_budget_category_with_no_history_is_not_deprioritised(client) -> None:
    token = _register_and_login(client, "reco-prior-brand-new@example.com")

    assert _create_budget(client, token, "Dining", "100.00").status_code == 201
    assert _create_transaction(client, token, "85.00", "Dining", "2026-07-05").status_code == 201

    resp = _recommendation(client, token)
    body = resp.json()
    assert body["type"] == "BUDGET_RISK"
    assert body["category"] == "Dining"
    assert body["deprioritization_reason"] is None
