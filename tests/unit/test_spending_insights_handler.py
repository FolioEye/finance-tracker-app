"""Unit tests for GetSpendingInsightsHandler (FINTRACK-19). Fake
in-memory repository stands in for SqlAlchemyTransactionRepository, same
pattern as tests/unit/test_budget_handlers.py's FakeTransactionRepository
-- but this fake also implements sum_by_month_for_user_in_range, which
that one didn't need.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from apps.api.application.queries.get_spending_insights import (
    DEFAULT_TREND_MONTHS,
    GetSpendingInsightsHandler,
    GetSpendingInsightsQuery,
)


class FakeTransactionRepository:
    """Backed by a flat list of (user_id, category, amount, txn_date)
    rows so tests can seed transactions across categories and months
    without a real DB. Implements exactly the two aggregate methods
    GetSpendingInsightsHandler calls.
    """

    def __init__(self) -> None:
        self.rows: list[tuple[uuid.UUID, str, Decimal, date]] = []

    def seed(self, user_id: uuid.UUID, category: str, amount: str, txn_date: date) -> None:
        self.rows.append((user_id, category, Decimal(amount), txn_date))

    async def sum_by_category_for_user_in_range(
        self, user_id: uuid.UUID, start_date: date, end_date: date
    ) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = {}
        for row_user_id, category, amount, txn_date in self.rows:
            if row_user_id != user_id or not (start_date <= txn_date < end_date):
                continue
            totals[category] = totals.get(category, Decimal("0")) + amount
        return totals

    async def sum_by_month_for_user_in_range(
        self, user_id: uuid.UUID, start_date: date, end_date: date
    ) -> dict[tuple[int, int], Decimal]:
        totals: dict[tuple[int, int], Decimal] = {}
        for row_user_id, _category, amount, txn_date in self.rows:
            if row_user_id != user_id or not (start_date <= txn_date < end_date):
                continue
            key = (txn_date.year, txn_date.month)
            totals[key] = totals.get(key, Decimal("0")) + amount
        return totals


@pytest.fixture
def transactions() -> FakeTransactionRepository:
    return FakeTransactionRepository()


# ---------------------------------------------------------------------------
# BA Gherkin scenario 1: current-month total + per-category breakdown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dashboard_totals_and_categorises_current_month_spending(
    transactions: FakeTransactionRepository,
) -> None:
    user_id = uuid.uuid4()
    transactions.seed(user_id, "Groceries", "200.00", date(2026, 7, 5))
    transactions.seed(user_id, "Dining", "150.00", date(2026, 7, 10))
    transactions.seed(user_id, "Transport", "100.00", date(2026, 7, 15))

    handler = GetSpendingInsightsHandler(transaction_repository=transactions, clock=lambda: date(2026, 7, 19))
    insights = await handler.handle(GetSpendingInsightsQuery(user_id=user_id))

    assert insights.current_month_total == Decimal("450.00")
    by_category = {item.category: item.total for item in insights.by_category}
    assert by_category == {
        "Groceries": Decimal("200.00"),
        "Dining": Decimal("150.00"),
        "Transport": Decimal("100.00"),
    }


# ---------------------------------------------------------------------------
# BA Gherkin scenario 2: new user with zero transactions -- empty state
# is valid, zeroed data, not an error.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_user_with_zero_transactions_gets_a_zeroed_not_broken_response(
    transactions: FakeTransactionRepository,
) -> None:
    user_id = uuid.uuid4()
    handler = GetSpendingInsightsHandler(transaction_repository=transactions, clock=lambda: date(2026, 7, 19))
    insights = await handler.handle(GetSpendingInsightsQuery(user_id=user_id))

    assert insights.current_month_total == Decimal("0")
    assert insights.by_category == []
    # Trend series still has one entry per month in range -- all zero,
    # never an empty/absent list the frontend would have to special-case.
    assert len(insights.monthly_trend) == DEFAULT_TREND_MONTHS
    assert all(item.total == Decimal("0") for item in insights.monthly_trend)


# ---------------------------------------------------------------------------
# BA Gherkin scenario 4: large transaction history -- totals still
# accurate. (Wall-clock timing is exercised at the integration level,
# not here -- this unit test only proves the aggregation logic itself
# doesn't lose or double-count rows at volume.)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_totals_remain_accurate_across_a_large_number_of_transactions(
    transactions: FakeTransactionRepository,
) -> None:
    user_id = uuid.uuid4()
    for i in range(1200):
        category = f"Category{i % 5}"
        transactions.seed(user_id, category, "1.00", date(2026, 7, 1))

    handler = GetSpendingInsightsHandler(transaction_repository=transactions, clock=lambda: date(2026, 7, 19))
    insights = await handler.handle(GetSpendingInsightsQuery(user_id=user_id))

    assert insights.current_month_total == Decimal("1200.00")
    assert len(insights.by_category) == 5
    assert sum((item.total for item in insights.by_category), Decimal("0")) == Decimal("1200.00")


# ---------------------------------------------------------------------------
# Gap-fill: monthly trend excludes prior-year-boundary spend correctly
# and fills zero-spend months with explicit zeros (not absent entries).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_monthly_trend_is_gap_free_across_a_year_boundary(
    transactions: FakeTransactionRepository,
) -> None:
    user_id = uuid.uuid4()
    transactions.seed(user_id, "Groceries", "50.00", date(2025, 12, 10))
    transactions.seed(user_id, "Groceries", "80.00", date(2026, 2, 5))
    # No transactions at all in January -- must still appear as a zero
    # entry in the trend, not be skipped.

    handler = GetSpendingInsightsHandler(transaction_repository=transactions, clock=lambda: date(2026, 2, 20))
    insights = await handler.handle(GetSpendingInsightsQuery(user_id=user_id, trend_months=3))

    trend_by_month = {(item.year, item.month): item.total for item in insights.monthly_trend}
    assert trend_by_month == {
        (2025, 12): Decimal("50.00"),
        (2026, 1): Decimal("0"),
        (2026, 2): Decimal("80.00"),
    }


@pytest.mark.asyncio
async def test_monthly_trend_respects_custom_trend_months(
    transactions: FakeTransactionRepository,
) -> None:
    user_id = uuid.uuid4()
    handler = GetSpendingInsightsHandler(transaction_repository=transactions, clock=lambda: date(2026, 7, 19))
    insights = await handler.handle(GetSpendingInsightsQuery(user_id=user_id, trend_months=3))
    assert [(item.year, item.month) for item in insights.monthly_trend] == [
        (2026, 5),
        (2026, 6),
        (2026, 7),
    ]


@pytest.mark.asyncio
async def test_current_month_total_excludes_prior_month_spend(
    transactions: FakeTransactionRepository,
) -> None:
    user_id = uuid.uuid4()
    transactions.seed(user_id, "Groceries", "999.00", date(2026, 6, 28))  # last month
    transactions.seed(user_id, "Groceries", "50.00", date(2026, 7, 2))  # this month

    handler = GetSpendingInsightsHandler(transaction_repository=transactions, clock=lambda: date(2026, 7, 19))
    insights = await handler.handle(GetSpendingInsightsQuery(user_id=user_id))
    assert insights.current_month_total == Decimal("50.00")


# ---------------------------------------------------------------------------
# Gap-fill: IDOR at the handler layer -- one user's data never leaks into
# another user's query result.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insights_are_scoped_per_user(transactions: FakeTransactionRepository) -> None:
    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    transactions.seed(user_a, "Groceries", "100.00", date(2026, 7, 10))
    transactions.seed(user_b, "Private", "999.00", date(2026, 7, 10))

    handler = GetSpendingInsightsHandler(transaction_repository=transactions, clock=lambda: date(2026, 7, 19))
    insights_a = await handler.handle(GetSpendingInsightsQuery(user_id=user_a))

    assert insights_a.current_month_total == Decimal("100.00")
    assert [item.category for item in insights_a.by_category] == ["Groceries"]
