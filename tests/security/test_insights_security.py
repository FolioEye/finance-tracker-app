"""QA Lead mandatory security sweep for FINTRACK-19 (Spending Insights
Dashboard), run at the real API level (TestClient -> real router -> real
Pydantic validation -> real handler -> real SQLite-backed repository).

Checklist (per fintrack-qa-lead skill, "any story touching auth, data, or
money"): SQL injection, XSS, auth bypass, IDOR. This endpoint is read-only
with no free-text request field at all -- category/amount/date are never
supplied by the caller, only produced from data the caller already owns
-- so there is no SQL injection or XSS input surface to test (unlike
budgets/transactions, which accept a free-text category). That absence
is itself asserted below rather than silently skipped. Auth bypass and
IDOR fully apply and are the substantive checks here, same structure as
tests/security/test_budgets_security.py.
"""
from __future__ import annotations

import uuid

import jwt as pyjwt


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


def _create_transaction(client, token: str, amount: str, category: str, transaction_date: str):
    return client.post(
        "/api/v1/transactions",
        json={"amount": amount, "category": category, "transaction_date": transaction_date},
        headers=_auth(token),
    )


def _dashboard(client, token: str | None = None, params: dict | None = None):
    headers = _auth(token) if token else {}
    return client.get("/api/v1/insights/dashboard", params=params or {}, headers=headers)


# ---------------------------------------------------------------------------
# No injectable free-text surface -- documented explicitly rather than
# silently skipped. The only caller-supplied input is trend_months, which
# is an integer bounded by FastAPI's Query(ge=1, le=24) before it ever
# reaches application code; a non-integer value is rejected by Pydantic
# coercion, never passed through to a query.
# ---------------------------------------------------------------------------


def test_non_integer_trend_months_is_rejected_by_validation_not_passed_to_a_query(client) -> None:
    token = _register_and_login(client, "insights-sqli-trend-months@example.com")
    resp = _dashboard(client, token, params={"trend_months": "1 OR 1=1"})
    assert resp.status_code == 422


def test_script_tag_in_trend_months_is_rejected_by_validation(client) -> None:
    token = _register_and_login(client, "insights-xss-trend-months@example.com")
    resp = _dashboard(client, token, params={"trend_months": "<script>alert(1)</script>"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Auth bypass
# ---------------------------------------------------------------------------


def test_auth_bypass_missing_token_rejected(client) -> None:
    resp = _dashboard(client)
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"


def test_auth_bypass_malformed_authorization_header_rejected(client) -> None:
    resp = client.get(
        "/api/v1/insights/dashboard", headers={"Authorization": "NotBearer sometoken"}
    )
    assert resp.status_code == 401


def test_auth_bypass_empty_bearer_token_rejected(client) -> None:
    resp = client.get("/api/v1/insights/dashboard", headers={"Authorization": "Bearer "})
    assert resp.status_code == 401


def test_auth_bypass_token_signed_with_wrong_secret_rejected(client) -> None:
    forged = pyjwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "jti": str(uuid.uuid4())},
        "attacker-controlled-wrong-secret",
        algorithm="HS256",
    )
    resp = client.get(
        "/api/v1/insights/dashboard", headers={"Authorization": f"Bearer {forged}"}
    )
    assert resp.status_code == 401


def test_auth_bypass_refresh_token_rejected_as_access_token(client) -> None:
    """A refresh-typed token presented as a bearer access token must be
    rejected -- same convention as get_current_user_id's existing
    handling for every other authenticated endpoint."""
    forged = pyjwt.encode(
        {"sub": str(uuid.uuid4()), "type": "refresh", "jti": str(uuid.uuid4())},
        "test-secret-key-not-for-production-use-only",
        algorithm="HS256",
    )
    resp = client.get(
        "/api/v1/insights/dashboard", headers={"Authorization": f"Bearer {forged}"}
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# IDOR -- there is no account-scoped path or body parameter for an
# attacker to manipulate at all (unlike budgets/transactions, which have
# a resource id in the URL). The only possible IDOR vector here is
# whether the response ever includes another user's data; both
# directions are checked.
# ---------------------------------------------------------------------------


def test_idor_dashboard_never_includes_another_users_categories(client) -> None:
    victim_token = _register_and_login(client, "insights-idor-sec-victim@example.com")
    attacker_token = _register_and_login(client, "insights-idor-sec-attacker@example.com")
    _create_transaction(client, victim_token, "500.00", "Private", "2026-07-10")

    attacker_resp = _dashboard(client, attacker_token)
    assert attacker_resp.status_code == 200
    categories = {item["category"] for item in attacker_resp.json()["by_category"]}
    assert "Private" not in categories
    assert attacker_resp.json()["current_month_total"] == "0"


def test_idor_dashboard_totals_are_not_inflated_by_other_users_spend(client) -> None:
    other_token = _register_and_login(client, "insights-idor-sec-other@example.com")
    my_token = _register_and_login(client, "insights-idor-sec-me@example.com")
    _create_transaction(client, other_token, "9999.00", "Groceries", "2026-07-10")
    _create_transaction(client, my_token, "25.00", "Groceries", "2026-07-10")

    my_resp = _dashboard(client, my_token)
    assert my_resp.json()["current_month_total"] == "25.00"
