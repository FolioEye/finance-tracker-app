"""QA Lead integration suite for FINTRACK-22 (Threshold-Based Alerts).
Same approach as tests/integration/test_budgets_api.py: hits the real
FastAPI app over HTTP via TestClient, backed by a genuine SQLite DB and
fakeredis (see tests/conftest.py).

Every scenario in tests/features/FINTRACK-22-threshold-alerts.feature
maps to a test function below, plus gap-fill for auth coverage and the
rolling-average window boundary (ROLLING_WINDOW=10, ADR-014 decision C).
"""
from __future__ import annotations

import uuid
from datetime import date

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


def _create_transaction(client, token: str, amount: str, category: str, transaction_date: str):
    resp = client.post(
        "/api/v1/transactions",
        json={"amount": amount, "category": category, "transaction_date": transaction_date},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp


def _list_alerts(client, token: str, include_dismissed: bool = False):
    params = {"include_dismissed": "true"} if include_dismissed else {}
    return client.get("/api/v1/alerts", headers=_auth(token), params=params)


def _dismiss(client, token: str, alert_id: str):
    return client.post(f"/api/v1/alerts/{alert_id}/dismiss", headers=_auth(token))


# ---------------------------------------------------------------------------
# Scenario 1: Category spend crosses the 90% threshold
# ---------------------------------------------------------------------------


def test_category_spend_crosses_the_90_percent_threshold(client) -> None:
    token = _register_and_login(client, "alert-cross-threshold@example.com")
    _create_budget(client, token, "Groceries", "400.00")
    _create_transaction(client, token, "350.00", "Groceries", "2026-07-10")  # 87.5% -- no alert yet

    assert _list_alerts(client, token).json()["items"] == []

    _create_transaction(client, token, "15.00", "Groceries", "2026-07-11")  # 365/400 = 91.25%

    items = _list_alerts(client, token).json()["items"]
    threshold_alerts = [a for a in items if a["alert_type"] == "THRESHOLD_CROSSING"]
    assert len(threshold_alerts) == 1
    assert threshold_alerts[0]["category"] == "Groceries"
    assert threshold_alerts[0]["threshold_pct"] == "90.00"


# ---------------------------------------------------------------------------
# Scenario 2: Spend stays well under threshold
# ---------------------------------------------------------------------------


def test_spend_stays_well_under_threshold(client) -> None:
    token = _register_and_login(client, "alert-under-threshold@example.com")
    _create_budget(client, token, "Groceries", "400.00")
    _create_transaction(client, token, "100.00", "Groceries", "2026-07-10")
    _create_transaction(client, token, "20.00", "Groceries", "2026-07-11")  # 120/400 = 30%

    items = _list_alerts(client, token).json()["items"]
    assert [a for a in items if a["alert_type"] == "THRESHOLD_CROSSING"] == []


# ---------------------------------------------------------------------------
# Scenario 3: Threshold is crossed multiple times via rapid transactions
# ---------------------------------------------------------------------------


def test_threshold_crossed_multiple_times_via_rapid_transactions_fires_only_once(client) -> None:
    token = _register_and_login(client, "alert-rapid-crossings@example.com")
    _create_budget(client, token, "Groceries", "100.00")
    _create_transaction(client, token, "91.00", "Groceries", "2026-07-10")  # crosses 90% -- 1st alert

    assert len(_list_alerts(client, token).json()["items"]) == 1

    for amount in ("1.00", "1.00", "1.00"):
        _create_transaction(client, token, amount, "Groceries", "2026-07-11")

    items = _list_alerts(client, token).json()["items"]
    threshold_alerts = [a for a in items if a["alert_type"] == "THRESHOLD_CROSSING"]
    assert len(threshold_alerts) == 1  # still just the one alert, not one per transaction


# ---------------------------------------------------------------------------
# Scenario 4: Alert data is scoped to the authenticated user only
# ---------------------------------------------------------------------------


def test_alert_data_is_scoped_to_the_authenticated_user_only(client) -> None:
    user_a_token = _register_and_login(client, "alert-scope-a@example.com")
    user_b_token = _register_and_login(client, "alert-scope-b@example.com")

    _create_budget(client, user_a_token, "Groceries", "100.00")
    _create_transaction(client, user_a_token, "95.00", "Groceries", "2026-07-10")

    a_items = _list_alerts(client, user_a_token).json()["items"]
    b_items = _list_alerts(client, user_b_token).json()["items"]
    assert len(a_items) == 1
    assert b_items == []


# ---------------------------------------------------------------------------
# Scenario 5: An unusually large single transaction triggers an alert
# ---------------------------------------------------------------------------


def test_an_unusually_large_single_transaction_triggers_an_alert(client) -> None:
    token = _register_and_login(client, "alert-large-txn@example.com")
    for amount in ("20.00", "18.00", "22.00"):
        _create_transaction(client, token, amount, "Dining", "2026-07-10")

    _create_transaction(client, token, "500.00", "Dining", "2026-07-15")

    items = _list_alerts(client, token).json()["items"]
    large_alerts = [a for a in items if a["alert_type"] == "LARGE_TRANSACTION"]
    assert len(large_alerts) == 1
    assert large_alerts[0]["category"] == "Dining"


# ---------------------------------------------------------------------------
# Scenario 6: A transaction within normal range does not trigger a
# large-transaction alert
# ---------------------------------------------------------------------------


def test_a_transaction_within_normal_range_does_not_trigger_a_large_transaction_alert(client) -> None:
    token = _register_and_login(client, "alert-normal-txn@example.com")
    for amount in ("40.00", "38.00", "42.00"):
        _create_transaction(client, token, amount, "Dining", "2026-07-10")

    _create_transaction(client, token, "45.00", "Dining", "2026-07-15")

    items = _list_alerts(client, token).json()["items"]
    assert [a for a in items if a["alert_type"] == "LARGE_TRANSACTION"] == []


# ---------------------------------------------------------------------------
# Scenario 7: Dismissing an alert does not suppress future alerts
# ---------------------------------------------------------------------------


async def test_dismissing_an_alert_does_not_suppress_future_alerts(client, test_session_factory) -> None:
    """Exercises AC4 at the real API/DB level across a simulated month
    boundary, using the same injected-clock override technique
    test_budgets_api.py's monthly-reset test uses (ADR-013 decision F /
    ADR-014 decision A) -- the evaluate-alerts handler's clock is pinned
    so July's crossing and August's crossing are genuinely different
    periods, not just two calls on the same day.
    """
    from fastapi import Depends

    from apps.api.application.commands.evaluate_alerts_for_transaction import (
        EvaluateAlertsForTransactionHandler,
    )
    from apps.api.infrastructure.repositories.sqlalchemy_alert_repository import (
        SqlAlchemyAlertRepository,
    )
    from apps.api.infrastructure.repositories.sqlalchemy_budget_repository import (
        SqlAlchemyBudgetRepository,
    )
    from apps.api.infrastructure.repositories.sqlalchemy_transaction_repository import (
        SqlAlchemyTransactionRepository,
    )
    from apps.api.main import app
    from apps.api.presentation.api.v1.dependencies import (
        get_db_session,
        get_evaluate_alerts_for_transaction_handler,
    )

    token = _register_and_login(client, "alert-dismiss-then-new-crossing@example.com")
    _create_budget(client, token, "Groceries", "100.00")

    def frozen_handler(pinned_date):
        # Depends on get_db_session (not a fresh test_session_factory()
        # session) so this override shares the SAME per-request cached
        # session as CreateTransactionHandler -- alert evaluation happens
        # inside the same still-open request as the transaction write, so
        # it must see the not-yet-committed row via the same session, the
        # same way the real, non-overridden dependency graph does.
        def _override(session=Depends(get_db_session)):
            return EvaluateAlertsForTransactionHandler(
                alert_repository=SqlAlchemyAlertRepository(session),
                budget_repository=SqlAlchemyBudgetRepository(session),
                transaction_repository=SqlAlchemyTransactionRepository(session),
                clock=lambda: pinned_date,
            )
        return _override

    # July: cross the threshold.
    app.dependency_overrides[get_evaluate_alerts_for_transaction_handler] = frozen_handler(date(2026, 7, 19))
    try:
        _create_transaction(client, token, "91.00", "Groceries", "2026-07-10")
    finally:
        del app.dependency_overrides[get_evaluate_alerts_for_transaction_handler]

    july_items = _list_alerts(client, token).json()["items"]
    assert len(july_items) == 1
    alert_id = july_items[0]["id"]

    dismiss_resp = _dismiss(client, token, alert_id)
    assert dismiss_resp.status_code == 204
    assert _list_alerts(client, token).json()["items"] == []  # dismissed alert hidden by default

    # August: a new period's crossing must still be able to fire, even
    # though last month's alert was never re-armed, only dismissed.
    app.dependency_overrides[get_evaluate_alerts_for_transaction_handler] = frozen_handler(date(2026, 8, 5))
    try:
        _create_transaction(client, token, "92.00", "Groceries", "2026-08-03")
    finally:
        del app.dependency_overrides[get_evaluate_alerts_for_transaction_handler]

    active_items = _list_alerts(client, token).json()["items"]
    assert len(active_items) == 1
    assert active_items[0]["period_start"] == "2026-08-01"

    all_items = _list_alerts(client, token, include_dismissed=True).json()["items"]
    assert len(all_items) == 2  # July's dismissed alert + August's new one


# ---------------------------------------------------------------------------
# Scenario 8: Attempt to dismiss another user's alert
# ---------------------------------------------------------------------------


def test_attempt_to_dismiss_another_users_alert(client) -> None:
    user_a_token = _register_and_login(client, "alert-idor-dismiss-a@example.com")
    user_b_token = _register_and_login(client, "alert-idor-dismiss-b@example.com")

    _create_budget(client, user_a_token, "Groceries", "100.00")
    _create_transaction(client, user_a_token, "95.00", "Groceries", "2026-07-10")
    alert_id = _list_alerts(client, user_a_token).json()["items"][0]["id"]

    resp = _dismiss(client, user_b_token, alert_id)
    assert resp.status_code == 404  # not 403 -- can't be used to confirm the id exists

    a_items = _list_alerts(client, user_a_token).json()["items"]
    assert len(a_items) == 1
    assert a_items[0]["dismissed_at"] is None  # untouched


# ---------------------------------------------------------------------------
# Gap-fill: auth required on every endpoint
# ---------------------------------------------------------------------------


def test_all_alert_endpoints_require_auth(client) -> None:
    assert client.get("/api/v1/alerts").status_code == 401
    assert client.post(f"/api/v1/alerts/{uuid.uuid4()}/dismiss").status_code == 401


# ---------------------------------------------------------------------------
# Gap-fill: dismissing a nonexistent alert returns 404
# ---------------------------------------------------------------------------


def test_dismissing_a_nonexistent_alert_returns_404(client) -> None:
    token = _register_and_login(client, "alert-dismiss-missing@example.com")
    resp = _dismiss(client, token, str(uuid.uuid4()))
    assert resp.status_code == 404


def test_dismissing_the_same_alert_twice_is_idempotent(client) -> None:
    token = _register_and_login(client, "alert-dismiss-twice@example.com")
    _create_budget(client, token, "Groceries", "100.00")
    _create_transaction(client, token, "95.00", "Groceries", "2026-07-10")
    alert_id = _list_alerts(client, token).json()["items"][0]["id"]

    assert _dismiss(client, token, alert_id).status_code == 204
    assert _dismiss(client, token, alert_id).status_code == 204  # second dismiss, still succeeds


# ---------------------------------------------------------------------------
# Gap-fill: rolling-average window boundary (ROLLING_WINDOW=10) -- proves
# the large-transaction baseline only considers the most recent 10
# transactions, not the full category history.
# ---------------------------------------------------------------------------


def test_large_transaction_baseline_only_considers_the_last_10_transactions(client) -> None:
    token = _register_and_login(client, "alert-rolling-window@example.com")

    # 5 old, large transactions -- must NOT count toward the average once
    # more than ROLLING_WINDOW (10) newer transactions exist.
    for _ in range(5):
        _create_transaction(client, token, "100.00", "Dining", "2026-07-01")

    # 10 recent, small transactions -- these are the only ones that should
    # feed the rolling average by the time the next transaction lands.
    for _ in range(10):
        _create_transaction(client, token, "5.00", "Dining", "2026-07-10")

    # If the window were NOT limited to 10, the average would be
    # (5*100 + 10*5)/15 = 36.67, and 3x that (110.0) would swallow a $20
    # transaction. With the window correctly limited to the last 10 ($5
    # each), the average is $5, so 3x = $15, and $20 must fire.
    resp = _create_transaction(client, token, "20.00", "Dining", "2026-07-15")
    new_txn_id = resp.json()["id"]

    items = _list_alerts(client, token).json()["items"]
    large_alerts = [a for a in items if a["alert_type"] == "LARGE_TRANSACTION" and a["transaction_id"] == new_txn_id]
    assert len(large_alerts) == 1


# ---------------------------------------------------------------------------
# Gap-fill: large dataset -- many categories each crossing threshold in
# one account, list endpoint stays correct and user-scoped at scale.
# ---------------------------------------------------------------------------


def test_alerts_list_is_correct_across_a_large_number_of_categories(client) -> None:
    token = _register_and_login(client, "alert-large-dataset@example.com")
    for i in range(20):
        category = f"Category{i}"
        _create_budget(client, token, category, "100.00")
        _create_transaction(client, token, "95.00", category, "2026-07-05")  # 95% -- crosses threshold

    items = _list_alerts(client, token).json()["items"]
    threshold_alerts = [a for a in items if a["alert_type"] == "THRESHOLD_CROSSING"]
    assert len(threshold_alerts) == 20
    assert {a["category"] for a in threshold_alerts} == {f"Category{i}" for i in range(20)}
