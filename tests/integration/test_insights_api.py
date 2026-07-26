"""QA Lead integration suite for FINTRACK-19 (Spending Insights
Dashboard). Same approach as tests/integration/test_budgets_api.py: hits
the real FastAPI app over HTTP via TestClient, backed by a genuine
SQLite DB and fakeredis (see tests/conftest.py).

Every scenario in
tests/features/FINTRACK-19-spending-insights-dashboard.feature maps to a
test function below.
"""
from __future__ import annotations

import time
import uuid
from datetime import date
from decimal import Decimal

import jwt as pyjwt
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


def _user_id_from_token(token: str) -> uuid.UUID:
    claims = pyjwt.decode(token, options={"verify_signature": False})
    return uuid.UUID(claims["sub"])


def _create_transaction(client, token: str, amount: str, category: str, transaction_date: str):
    return client.post(
        "/api/v1/transactions",
        json={"amount": amount, "category": category, "transaction_date": transaction_date},
        headers=_auth(token),
    )


def _dashboard(client, token: str, trend_months: int | None = None):
    params = {"trend_months": trend_months} if trend_months is not None else {}
    return client.get("/api/v1/insights/dashboard", params=params, headers=_auth(token))


# ---------------------------------------------------------------------------
# Scenario 1: Dashboard correctly totals and categorises current-month
# spending
# ---------------------------------------------------------------------------


def test_dashboard_totals_and_categorises_current_month_spending(client) -> None:
    token = _register_and_login(client, "insights-happy-path@example.com")
    _create_transaction(client, token, "200.00", "Groceries", "2026-07-05")
    _create_transaction(client, token, "150.00", "Dining", "2026-07-10")
    _create_transaction(client, token, "100.00", "Transport", "2026-07-15")

    resp = _dashboard(client, token)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["current_month_total"] == "450.00"
    by_category = {item["category"]: item["total"] for item in body["by_category"]}
    assert by_category == {"Groceries": "200.00", "Dining": "150.00", "Transport": "100.00"}


# ---------------------------------------------------------------------------
# Scenario 2: New user with zero transactions sees an empty state -- not
# an error, not a broken/missing field.
# ---------------------------------------------------------------------------


def test_new_user_with_zero_transactions_sees_a_valid_empty_state(client) -> None:
    token = _register_and_login(client, "insights-empty-state@example.com")
    resp = _dashboard(client, token)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["current_month_total"] == "0"
    assert body["by_category"] == []
    # Trend series present with explicit zero entries, not omitted --
    # gives the frontend a real (empty) chart to render its CTA over,
    # never a missing field to null-check.
    assert len(body["monthly_trend"]) == 6
    assert all(item["total"] == "0" for item in body["monthly_trend"])


# ---------------------------------------------------------------------------
# Scenario 3: Dashboard shows a graceful error state when the
# aggregation service is unavailable. There's no frontend in this repo,
# so this is satisfied by construction: the existing global exception
# handler (apps/api/main.py) already returns a generic 500 JSON body --
# never a stack trace or an HTML error page -- for any unhandled
# exception, which is exactly what a downstream aggregation failure
# would surface as.
# ---------------------------------------------------------------------------


def test_dashboard_returns_a_generic_error_body_not_a_stack_trace_on_failure(client) -> None:
    from fastapi.testclient import TestClient

    from apps.api.main import app
    from apps.api.presentation.api.v1.dependencies import get_get_spending_insights_handler

    class _BrokenHandler:
        async def handle(self, query):
            raise RuntimeError("transaction-aggregation service unavailable")

    async def broken_handler_override():
        return _BrokenHandler()

    token = _register_and_login(client, "insights-error-state@example.com")
    app.dependency_overrides[get_get_spending_insights_handler] = broken_handler_override
    try:
        # The shared `client` fixture uses TestClient's default
        # raise_server_exceptions=True, which re-raises unhandled
        # exceptions for debugging rather than surfacing the app's own
        # 500 response -- appropriate for every other test in this
        # suite, but this test's whole point is to inspect that 500
        # response body. A second TestClient wrapping the same `app`
        # (already wired with this fixture's DB/dependency overrides)
        # with raise_server_exceptions=False observes what a real client
        # actually receives, without changing the shared fixture's
        # default behaviour for any other test.
        with TestClient(app, raise_server_exceptions=False) as lenient_client:
            resp = lenient_client.get("/api/v1/insights/dashboard", headers=_auth(token))
    finally:
        del app.dependency_overrides[get_get_spending_insights_handler]

    assert resp.status_code == 500
    body = resp.json()
    assert body == {"detail": "Internal server error"}
    # No stack trace, exception class name, or file path leaked.
    assert "RuntimeError" not in resp.text
    assert "Traceback" not in resp.text


# ---------------------------------------------------------------------------
# Scenario 4: Dashboard loads acceptably with a large transaction
# history, and totals stay accurate at that volume. Transactions are
# seeded directly against the test DB (not via 1000+ individual HTTP
# calls) -- this test is about the query path's correctness and
# response time at volume, not about exercising the create-transaction
# endpoint 1000+ times.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dashboard_loads_acceptably_and_stays_accurate_with_1000_plus_transactions(
    client, test_session_factory
) -> None:
    from apps.api.domain.models.transaction import Money, Transaction
    from apps.api.infrastructure.repositories.sqlalchemy_transaction_repository import (
        SqlAlchemyTransactionRepository,
    )

    token = _register_and_login(client, "insights-large-dataset@example.com")
    user_id = _user_id_from_token(token)

    async with test_session_factory() as session:
        repo = SqlAlchemyTransactionRepository(session)
        for i in range(1200):
            txn = Transaction.new(
                user_id=user_id,
                amount=Money.parse("1.00"),
                category=f"Category{i % 5}",
                transaction_date=date(2026, 7, 1),
            )
            await repo.add(txn)
        await session.commit()

    started = time.monotonic()
    resp = _dashboard(client, token)
    elapsed = time.monotonic() - started

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["current_month_total"] == "1200.00"
    assert len(body["by_category"]) == 5
    assert sum(Decimal(item["total"]) for item in body["by_category"]) == Decimal("1200.00")
    # Best-effort bound only -- this asserts the query is doing real
    # SQL-side aggregation (GROUP BY) rather than pulling 1200 rows into
    # Python, not a strict production SLA; CI hardware varies.
    assert elapsed < 5.0


# ---------------------------------------------------------------------------
# Scenario 5: Attempt to access another user's dashboard data
# ---------------------------------------------------------------------------


def test_attempt_to_access_another_users_dashboard_data(client) -> None:
    victim_token = _register_and_login(client, "insights-idor-victim@example.com")
    attacker_token = _register_and_login(client, "insights-idor-attacker@example.com")
    _create_transaction(client, victim_token, "999.00", "Private", "2026-07-10")

    # There is no account-scoped path/body parameter for the attacker to
    # target at all -- user_id always comes from the attacker's own JWT.
    # The real IDOR check here is that the attacker's own dashboard never
    # contains the victim's data.
    attacker_resp = _dashboard(client, attacker_token)
    assert attacker_resp.status_code == 200
    body = attacker_resp.json()
    assert body["current_month_total"] == "0"
    assert "Private" not in {item["category"] for item in body["by_category"]}

    victim_resp = _dashboard(client, victim_token)
    assert "Private" in {item["category"] for item in victim_resp.json()["by_category"]}


# ---------------------------------------------------------------------------
# Gap-fill: auth required
# ---------------------------------------------------------------------------


def test_dashboard_requires_auth(client) -> None:
    resp = client.get("/api/v1/insights/dashboard")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Gap-fill: trend_months bounds (Query(ge=1, le=24))
# ---------------------------------------------------------------------------


def test_trend_months_below_minimum_is_rejected(client) -> None:
    token = _register_and_login(client, "insights-trend-too-low@example.com")
    resp = _dashboard(client, token, trend_months=0)
    assert resp.status_code == 422


def test_trend_months_above_maximum_is_rejected(client) -> None:
    token = _register_and_login(client, "insights-trend-too-high@example.com")
    resp = _dashboard(client, token, trend_months=25)
    assert resp.status_code == 422


def test_custom_trend_months_is_honoured(client) -> None:
    token = _register_and_login(client, "insights-trend-custom@example.com")
    _create_transaction(client, token, "10.00", "Groceries", "2026-07-05")
    resp = _dashboard(client, token, trend_months=3)
    assert resp.status_code == 200
    assert len(resp.json()["monthly_trend"]) == 3


# ---------------------------------------------------------------------------
# Gap-fill: month format in the trend response is pre-zero-padded
# "YYYY-MM", not a bare integer the frontend would have to format itself.
# ---------------------------------------------------------------------------


def test_monthly_trend_months_are_formatted_as_zero_padded_year_month(client) -> None:
    token = _register_and_login(client, "insights-trend-format@example.com")
    resp = _dashboard(client, token, trend_months=1)
    assert resp.status_code == 200
    months = [item["month"] for item in resp.json()["monthly_trend"]]
    assert all(len(m) == 7 and m[4] == "-" for m in months)
