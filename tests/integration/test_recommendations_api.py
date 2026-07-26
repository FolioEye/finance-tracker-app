"""QA Lead integration suite for FINTRACK-21 (Weekly Recommendation
Engine). Same approach as tests/integration/test_insights_api.py: hits
the real FastAPI app over HTTP via TestClient, backed by a genuine
SQLite DB and fakeredis (see tests/conftest.py).

Every scenario in
tests/features/FINTRACK-21-weekly-recommendation-engine.feature maps to
a test function below. Budget and transaction state is created through
the real API (POST /api/v1/budgets, POST /api/v1/transactions), same
"set up via API calls" convention as every prior story's integration
suite. Subscription state cannot be created directly (there's no POST
/api/v1/subscriptions endpoint by design -- subscriptions are only ever
system-detected, per FINTRACK-18) so the subscription-triggered scenarios
below create three same-merchant transactions ~30 days apart, which is
exactly what DetectSubscriptionsForTransactionHandler (wired into
POST /api/v1/transactions) needs to auto-detect a DETECTED-status row --
the real end-to-end path, not a shortcut around it.
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


def _create_budget(client, token: str, category: str, monthly_limit: str):
    return client.post(
        "/api/v1/budgets",
        json={"category": category, "monthly_limit": monthly_limit},
        headers=_auth(token),
    )


def _create_transaction(
    client, token: str, amount: str, category: str, transaction_date: str, note: str | None = None
):
    body = {"amount": amount, "category": category, "transaction_date": transaction_date}
    if note is not None:
        body["note"] = note
    return client.post("/api/v1/transactions", json=body, headers=_auth(token))


def _recommendation(client, token: str | None = None):
    headers = _auth(token) if token else {}
    return client.get("/api/v1/recommendations/weekly", headers=headers)


# ---------------------------------------------------------------------------
# Wiring smoke test -- proves the route, DI factory, and handler are all
# actually connected end to end. This is the exact regression the Tech
# Lead push originally broke (a missing DI factory made every test
# collection fail) -- kept as an explicit, named test rather than only
# relying on "some other test happens to hit this route."
# ---------------------------------------------------------------------------


def test_endpoint_is_wired_and_returns_a_neutral_recommendation_for_a_fresh_user(client) -> None:
    token = _register_and_login(client, "reco-wiring@example.com")
    resp = _recommendation(client, token)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["type"] == "NEUTRAL"
    assert body["category"] is None
    assert body["merchant"] is None


# ---------------------------------------------------------------------------
# BA Gherkin scenario 1: budget risk, created via the real budgets +
# transactions API
# ---------------------------------------------------------------------------


def test_budget_risk_recommendation_via_real_api(client) -> None:
    token = _register_and_login(client, "reco-budget-risk@example.com")
    assert _create_budget(client, token, "Dining", "100.00").status_code == 201
    assert (
        _create_transaction(client, token, "85.00", "Dining", "2026-07-05").status_code == 201
    )

    resp = _recommendation(client, token)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["type"] == "BUDGET_RISK"
    assert body["category"] == "Dining"


# ---------------------------------------------------------------------------
# BA Gherkin scenario 3: new subscription, via the real end-to-end
# detection path (three same-merchant transactions ~30 days apart)
# ---------------------------------------------------------------------------


def test_new_subscription_recommendation_via_real_detection_path(client) -> None:
    token = _register_and_login(client, "reco-new-sub@example.com")
    base = date(2026, 6, 20)
    for i in range(3):
        resp = _create_transaction(
            client,
            token,
            "15.99",
            "Entertainment",
            (base + timedelta(days=30 * i)).isoformat(),
            note="NETFLIX.COM",
        )
        assert resp.status_code == 201, resp.text

    resp = _recommendation(client, token)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["type"] == "NEW_SUBSCRIPTION"
    assert body["merchant"] == "NETFLIX.COM"


# ---------------------------------------------------------------------------
# BA Gherkin scenario 6: scoped to the authenticated user only
# ---------------------------------------------------------------------------


def test_idor_recommendation_never_reflects_another_users_budget(client) -> None:
    victim_token = _register_and_login(client, "reco-idor-victim@example.com")
    attacker_token = _register_and_login(client, "reco-idor-attacker@example.com")
    assert _create_budget(client, victim_token, "Private", "50.00").status_code == 201
    assert (
        _create_transaction(client, victim_token, "49.00", "Private", "2026-07-05").status_code
        == 201
    )

    attacker_resp = _recommendation(client, attacker_token)
    assert attacker_resp.status_code == 200, attacker_resp.text
    body = attacker_resp.json()
    assert body["type"] == "NEUTRAL"
    assert body["category"] is None


# ---------------------------------------------------------------------------
# Auth required at all -- no token, no data.
# ---------------------------------------------------------------------------


def test_auth_required_to_view_recommendation(client) -> None:
    resp = _recommendation(client)
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"
