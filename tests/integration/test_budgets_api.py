"""QA Lead integration suite for FINTRACK-20 (Simple Budget Tracking).
Same approach as tests/integration/test_categorisation_rules_api.py: hits
the real FastAPI app over HTTP via TestClient, backed by a genuine SQLite
DB and fakeredis (see tests/conftest.py).

Every scenario in tests/features/FINTRACK-20-simple-budget-tracking.feature
maps to a test function below.
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
    return client.post(
        "/api/v1/transactions",
        json={"amount": amount, "category": category, "transaction_date": transaction_date},
        headers=_auth(token),
    )


def _overview(client, token: str):
    return client.get("/api/v1/budgets", headers=_auth(token))


def _overview_by_category(client, token: str) -> dict:
    return {item["category"]: item for item in _overview(client, token).json()["items"]}


# ---------------------------------------------------------------------------
# Scenario 1: Track spend against a category budget
# ---------------------------------------------------------------------------


def test_track_spend_against_a_category_budget(client) -> None:
    token = _register_and_login(client, "budget-track-spend@example.com")
    create_resp = _create_budget(client, token, "Groceries", "500.00")
    assert create_resp.status_code == 201, create_resp.text

    txn_resp = _create_transaction(client, token, "300.00", "Groceries", "2026-07-15")
    assert txn_resp.status_code == 201, txn_resp.text

    items = _overview_by_category(client, token)
    assert items["Groceries"]["monthly_limit"] == "500.00"
    assert items["Groceries"]["spent"] == "300.00"
    assert items["Groceries"]["percent_used"] == "60.00"


# ---------------------------------------------------------------------------
# Scenario 2: Attempt to set an invalid budget limit
# ---------------------------------------------------------------------------


def test_attempt_to_set_an_invalid_budget_limit_zero(client) -> None:
    token = _register_and_login(client, "budget-invalid-zero@example.com")
    resp = _create_budget(client, token, "Dining", "0")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Budget must be a positive amount"
    assert _overview_by_category(client, token) == {}


def test_attempt_to_set_an_invalid_budget_limit_negative(client) -> None:
    token = _register_and_login(client, "budget-invalid-negative@example.com")
    resp = _create_budget(client, token, "Dining", "-50.00")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Budget must be a positive amount"
    assert _overview_by_category(client, token) == {}


# ---------------------------------------------------------------------------
# Scenario 3: Spending exceeds the category budget
# ---------------------------------------------------------------------------


def test_spending_exceeds_the_category_budget(client) -> None:
    token = _register_and_login(client, "budget-over-budget@example.com")
    _create_budget(client, token, "Entertainment", "200.00")
    _create_transaction(client, token, "250.00", "Entertainment", "2026-07-10")

    items = _overview_by_category(client, token)
    assert items["Entertainment"]["is_over_budget"] is True
    # Not silently capped at 100% -- the real overage is visible.
    assert items["Entertainment"]["percent_used"] == "125.00"


# ---------------------------------------------------------------------------
# Scenario 4: Attempt to access another user's budget data
# ---------------------------------------------------------------------------


def test_attempt_to_access_another_users_budget_data(client) -> None:
    user_a_token = _register_and_login(client, "budget-idor-a@example.com")
    user_b_token = _register_and_login(client, "budget-idor-b@example.com")

    create_resp = _create_budget(client, user_a_token, "Private", "100.00")
    budget_id = create_resp.json()["id"]

    edit_resp = client.patch(
        f"/api/v1/budgets/{budget_id}", json={"monthly_limit": "1.00"}, headers=_auth(user_b_token)
    )
    assert edit_resp.status_code == 404

    delete_resp = client.delete(f"/api/v1/budgets/{budget_id}", headers=_auth(user_b_token))
    assert delete_resp.status_code == 404

    # Overview isolation too -- User B never sees User A's category at all.
    assert "Private" in _overview_by_category(client, user_a_token)
    assert "Private" not in _overview_by_category(client, user_b_token)


# ---------------------------------------------------------------------------
# Scenario 5: Budget progress resets at the start of a new calendar month
# ---------------------------------------------------------------------------


async def test_budget_progress_resets_at_the_start_of_a_new_calendar_month(
    client, test_session_factory
) -> None:
    """Exercises AC3 at the real API/DB level. Pins "today" to 2026-07-19
    by overriding the get_get_budget_overview_handler dependency with an
    injected clock (ADR-013 decision F), same technique the client
    fixture already uses to override get_db_session -- everything else
    (routing, auth, real SQLite writes) stays on the real path.
    """
    from apps.api.main import app
    from apps.api.application.queries.get_budget_overview import GetBudgetOverviewHandler
    from apps.api.infrastructure.repositories.sqlalchemy_budget_repository import (
        SqlAlchemyBudgetRepository,
    )
    from apps.api.infrastructure.repositories.sqlalchemy_transaction_repository import (
        SqlAlchemyTransactionRepository,
    )
    from apps.api.presentation.api.v1.dependencies import get_get_budget_overview_handler

    token = _register_and_login(client, "budget-monthly-reset@example.com")
    _create_budget(client, token, "Groceries", "500.00")
    _create_transaction(client, token, "450.00", "Groceries", "2026-06-15")  # last month
    _create_transaction(client, token, "100.00", "Groceries", "2026-07-10")  # this month

    async def frozen_overview_handler():
        async with test_session_factory() as session:
            yield GetBudgetOverviewHandler(
                budget_repository=SqlAlchemyBudgetRepository(session),
                transaction_repository=SqlAlchemyTransactionRepository(session),
                clock=lambda: date(2026, 7, 19),
            )

    app.dependency_overrides[get_get_budget_overview_handler] = frozen_overview_handler
    try:
        resp = client.get("/api/v1/budgets", headers=_auth(token))
    finally:
        del app.dependency_overrides[get_get_budget_overview_handler]

    assert resp.status_code == 200, resp.text
    items = {i["category"]: i for i in resp.json()["items"]}
    assert items["Groceries"]["spent"] == "100.00"  # June's 450 excluded
    assert items["Groceries"]["percent_used"] == "20.00"


# ---------------------------------------------------------------------------
# Scenario 6: User edits an existing budget limit
# ---------------------------------------------------------------------------


def test_user_edits_an_existing_budget_limit(client) -> None:
    token = _register_and_login(client, "budget-edit@example.com")
    create_resp = _create_budget(client, token, "Groceries", "500.00")
    budget_id = create_resp.json()["id"]

    edit_resp = client.patch(
        f"/api/v1/budgets/{budget_id}", json={"monthly_limit": "600.00"}, headers=_auth(token)
    )
    assert edit_resp.status_code == 200, edit_resp.text
    assert edit_resp.json()["monthly_limit"] == "600.00"

    items = _overview_by_category(client, token)
    assert items["Groceries"]["monthly_limit"] == "600.00"


def test_editing_a_budget_recalculates_percentage_against_the_new_limit(client) -> None:
    token = _register_and_login(client, "budget-edit-recalc@example.com")
    create_resp = _create_budget(client, token, "Groceries", "500.00")
    budget_id = create_resp.json()["id"]
    _create_transaction(client, token, "300.00", "Groceries", "2026-07-15")

    assert _overview_by_category(client, token)["Groceries"]["percent_used"] == "60.00"

    client.patch(f"/api/v1/budgets/{budget_id}", json={"monthly_limit": "300.00"}, headers=_auth(token))

    items = _overview_by_category(client, token)
    assert items["Groceries"]["percent_used"] == "100.00"
    assert items["Groceries"]["is_over_budget"] is False  # exactly at limit, not over


def test_editing_a_nonexistent_budget_returns_404(client) -> None:
    token = _register_and_login(client, "budget-edit-missing@example.com")
    resp = client.patch(
        f"/api/v1/budgets/{uuid.uuid4()}", json={"monthly_limit": "100.00"}, headers=_auth(token)
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Scenario 7: User removes an existing budget
# ---------------------------------------------------------------------------


def test_user_removes_an_existing_budget(client) -> None:
    token = _register_and_login(client, "budget-remove@example.com")
    create_resp = _create_budget(client, token, "Groceries", "500.00")
    budget_id = create_resp.json()["id"]
    _create_transaction(client, token, "300.00", "Groceries", "2026-07-15")

    delete_resp = client.delete(f"/api/v1/budgets/{budget_id}", headers=_auth(token))
    assert delete_resp.status_code == 204

    items = _overview_by_category(client, token)
    assert items["Groceries"]["budget_id"] is None
    assert items["Groceries"]["monthly_limit"] is None
    # Past spend remains visible.
    assert items["Groceries"]["spent"] == "300.00"

    txn_list = client.get("/api/v1/transactions", headers=_auth(token))
    assert len(txn_list.json()["items"]) == 1


def test_deleting_a_budget_twice_returns_404_the_second_time(client) -> None:
    token = _register_and_login(client, "budget-delete-twice@example.com")
    create_resp = _create_budget(client, token, "Groceries", "500.00")
    budget_id = create_resp.json()["id"]

    assert client.delete(f"/api/v1/budgets/{budget_id}", headers=_auth(token)).status_code == 204
    assert client.delete(f"/api/v1/budgets/{budget_id}", headers=_auth(token)).status_code == 404


# ---------------------------------------------------------------------------
# Scenario 8: Category with no budget set shows spend without a false
# "over" state (AC5)
# ---------------------------------------------------------------------------


def test_category_with_no_budget_set_shows_spend_without_a_false_over_state(client) -> None:
    token = _register_and_login(client, "budget-no-budget-category@example.com")
    _create_transaction(client, token, "120.00", "Entertainment", "2026-07-10")

    items = _overview_by_category(client, token)
    assert items["Entertainment"]["spent"] == "120.00"
    assert items["Entertainment"]["budget_id"] is None
    assert items["Entertainment"]["monthly_limit"] is None
    assert items["Entertainment"]["percent_used"] is None
    assert items["Entertainment"]["is_over_budget"] is False


# ---------------------------------------------------------------------------
# Gap-fill: create is rejected for a duplicate category (edit-vs-create
# are distinct operations per ADR-013 decision C)
# ---------------------------------------------------------------------------


def test_creating_a_second_budget_for_the_same_category_returns_409(client) -> None:
    token = _register_and_login(client, "budget-duplicate@example.com")
    first = _create_budget(client, token, "Groceries", "500.00")
    assert first.status_code == 201
    second = _create_budget(client, token, "Groceries", "600.00")
    assert second.status_code == 409


# ---------------------------------------------------------------------------
# Gap-fill: auth required on every endpoint
# ---------------------------------------------------------------------------


def test_all_budget_endpoints_require_auth(client) -> None:
    assert client.post("/api/v1/budgets", json={"category": "Groceries", "monthly_limit": "500.00"}).status_code == 401
    assert client.get("/api/v1/budgets").status_code == 401
    assert client.patch(f"/api/v1/budgets/{uuid.uuid4()}", json={"monthly_limit": "1.00"}).status_code == 401
    assert client.delete(f"/api/v1/budgets/{uuid.uuid4()}").status_code == 401


# ---------------------------------------------------------------------------
# Gap-fill: overview correctness at scale (many budgeted + many
# unbudgeted-with-spend categories in one response)
# ---------------------------------------------------------------------------


def test_overview_is_correct_across_a_large_number_of_categories(client) -> None:
    token = _register_and_login(client, "budget-large-dataset@example.com")
    for i in range(30):
        _create_budget(client, token, f"Category{i}", "1000.00")
        _create_transaction(client, token, f"{i + 1}.00", f"Category{i}", "2026-07-05")
    for i in range(30, 50):
        # No budget for these -- spend-only rows (AC5).
        _create_transaction(client, token, f"{i + 1}.00", f"Category{i}", "2026-07-05")

    items = _overview_by_category(client, token)
    assert len(items) == 50
    assert items["Category0"]["spent"] == "1.00"
    assert items["Category0"]["monthly_limit"] == "1000.00"
    assert items["Category35"]["budget_id"] is None
    assert items["Category35"]["spent"] == "36.00"
