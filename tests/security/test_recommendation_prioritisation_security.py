"""QA Lead mandatory security sweep for FINTRACK-27 (Recommendation
Prioritisation from Follow-Through Outcomes), run at the real API level
(TestClient -> real router -> real handler -> real SQLite-backed
repositories).

Per BA's own note on the signed Gherkin
(tests/features/FINTRACK-27-recommendation-prioritisation.feature): this
story adds no new user-supplied input field at all (it's a backend
reordering of existing recommendations, with no new request body, path,
or query parameter) -- the standard SQL injection / XSS input-surface
template doesn't apply, same reasoning
tests/security/test_recommendations_security.py already documented for
the underlying endpoint. AC5 (per-user isolation of follow-through
history) is this story's mandatory security scenario instead.

Auth bypass on GET /recommendations/weekly is unchanged by this story
(same JWT dependency, same router) and already has full coverage in
test_recommendations_security.py -- not duplicated here.
"""
from __future__ import annotations

import uuid as uuid_mod
from datetime import date, datetime, timedelta, timezone

import jwt as pyjwt
import pytest

from apps.api.config import get_settings


def _this_month(day: int) -> str:
    """A date within the real current calendar month. See the identical
    helper's docstring in tests/integration/test_budgets_api.py for why
    this replaced hardcoded "2026-07-XX" literals (FINTRACK-38 Bug)."""
    return date.today().replace(day=day).isoformat()


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


async def _seed_history(
    test_session_factory,
    user_id: str,
    recommendation_type: str,
    recommendation_key: str,
    statuses_oldest_first: list[str],
    days_ago_start: int = 20,
) -> None:
    from apps.api.infrastructure.database.models import FollowThroughRecordModel

    for i, status in enumerate(statuses_oldest_first):
        days_ago = days_ago_start - i
        async with test_session_factory() as session:
            session.add(
                FollowThroughRecordModel(
                    id=uuid_mod.uuid4(),
                    user_id=uuid_mod.UUID(user_id),
                    period_start=date.today() - timedelta(days=days_ago),
                    recommendation_type=recommendation_type,
                    recommendation_key=recommendation_key,
                    status=status,
                    created_at=datetime.now(timezone.utc),
                    actioned_at=None,
                )
            )
            await session.commit()


# ---------------------------------------------------------------------------
# AC5: one user's follow-through history never influences another user's
# recommendation priority
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_alices_low_follow_through_never_deprioritises_bobs_own_recommendation(
    client, test_session_factory
) -> None:
    """Alice and Bob both have a \"Dining\" budget at risk. Alice has
    ignored her Dining budget-risk recommendations (would be
    deprioritised for her); Bob has a completely clean history (no
    follow-through data at all). Bob's own recommendation must be
    computed purely from his own (empty) history -- never from Alice's --
    so Bob's Dining category must still win normally, not be affected by
    Alice's low rate on the exact same category name.
    """
    alice_token = _register_and_login(client, "reco-prior-sec-alice@example.com")
    bob_token = _register_and_login(client, "reco-prior-sec-bob@example.com")
    alice_id = _decode_user_id(alice_token)

    assert _create_budget(client, alice_token, "Dining", "100.00").status_code == 201
    assert _create_transaction(client, alice_token, "90.00", "Dining", _this_month(5)).status_code == 201
    await _seed_history(
        test_session_factory, alice_id, "BUDGET_RISK", "Dining",
        ["DONE"] * 2 + ["IGNORED"] * 8, days_ago_start=20,
    )

    assert _create_budget(client, bob_token, "Dining", "100.00").status_code == 201
    assert _create_transaction(client, bob_token, "90.00", "Dining", _this_month(5)).status_code == 201

    bob_resp = _recommendation(client, bob_token)
    assert bob_resp.status_code == 200, bob_resp.text
    bob_body = bob_resp.json()
    # Bob has no history at all on "Dining" -- must be treated as brand-new
    # (not deprioritised), regardless of Alice's identical-category history.
    assert bob_body["type"] == "BUDGET_RISK"
    assert bob_body["category"] == "Dining"
    assert bob_body["deprioritization_reason"] is None


@pytest.mark.asyncio
async def test_bobs_high_follow_through_never_leaks_into_alices_computation(
    client, test_session_factory
) -> None:
    """Converse direction: Bob has a strong (normal-priority) history on
    \"Dining\"; Alice's own history on the same category name is poor.
    Alice must still be deprioritised on her own merits -- Bob's good
    record must never be read, joined, or applied to Alice's computation.
    """
    alice_token = _register_and_login(client, "reco-prior-sec-alice2@example.com")
    bob_token = _register_and_login(client, "reco-prior-sec-bob2@example.com")
    alice_id = _decode_user_id(alice_token)
    bob_id = _decode_user_id(bob_token)

    assert _create_budget(client, bob_token, "Dining", "100.00").status_code == 201
    assert _create_transaction(client, bob_token, "90.00", "Dining", _this_month(5)).status_code == 201
    await _seed_history(
        test_session_factory, bob_id, "BUDGET_RISK", "Dining",
        ["DONE"] * 8 + ["DISMISSED"] * 2, days_ago_start=20,
    )

    assert _create_budget(client, alice_token, "Dining", "100.00").status_code == 201
    assert _create_budget(client, alice_token, "Groceries", "100.00").status_code == 201
    assert _create_transaction(client, alice_token, "90.00", "Dining", _this_month(5)).status_code == 201
    assert _create_transaction(client, alice_token, "85.00", "Groceries", _this_month(5)).status_code == 201
    await _seed_history(
        test_session_factory, alice_id, "BUDGET_RISK", "Dining",
        ["DONE"] * 2 + ["IGNORED"] * 8, days_ago_start=20,
    )
    await _seed_history(
        test_session_factory, alice_id, "BUDGET_RISK", "Groceries",
        ["DONE"] * 8 + ["DISMISSED"] * 2, days_ago_start=40,
    )

    alice_resp = _recommendation(client, alice_token)
    assert alice_resp.status_code == 200, alice_resp.text
    alice_body = alice_resp.json()
    # Alice's Dining (native top pick, 90% used) is deprioritised on her
    # own poor record -- Groceries (85% used, normal) should win instead,
    # exactly as it would if Bob didn't exist at all.
    assert alice_body["category"] == "Groceries"
    assert alice_body["deprioritization_reason"] is not None
    assert "Dining" in alice_body["deprioritization_reason"]


def test_follow_through_history_endpoint_never_exposes_another_users_prioritisation_data(
    client,
) -> None:
    """Baseline IDOR check specific to this story's new data: the follow-
    through history endpoint (which recommendation_key values feed) must
    never return another user's rows -- already covered generally by
    test_follow_through_security.py, re-asserted here because
    recommendation_key is new data on that same response."""
    victim_token = _register_and_login(client, "reco-prior-sec-key-victim@example.com")
    attacker_token = _register_and_login(client, "reco-prior-sec-key-attacker@example.com")

    assert _create_budget(client, victim_token, "SecretCategory", "100.00").status_code == 201
    assert (
        _create_transaction(client, victim_token, "90.00", "SecretCategory", _this_month(5)).status_code
        == 201
    )
    _recommendation(client, victim_token)  # creates today's follow-through record

    attacker_history = client.get(
        "/api/v1/follow-through", headers=_auth(attacker_token)
    ).json()["items"]
    assert attacker_history == []
