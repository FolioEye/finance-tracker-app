"""GetSpendingInsightsQuery + handler -- covers AC1 (current-month total
and per-category breakdown) and AC2/AC4 (multi-month trend, large-dataset
performance). Story: FINTRACK-19.

Both aggregates are computed via SQL SUM/GROUP BY pushed to the database
-- never by loading every transaction into Python -- same principle
GetBudgetOverviewHandler already applies (see
docs/adr/ADR-013-budget-tracking-compute-on-read.md's precedent for
compute-on-read over a scheduled job or snapshot table).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date as date_type
from decimal import Decimal
from typing import Callable

from apps.api.application.queries.date_ranges import (
    current_month_bounds,
    month_sequence,
    trailing_months_bounds,
)
from apps.api.domain.repositories.transaction_repository import TransactionRepository

DEFAULT_TREND_MONTHS = 6


@dataclass(frozen=True)
class GetSpendingInsightsQuery:
    user_id: uuid.UUID
    trend_months: int = DEFAULT_TREND_MONTHS


@dataclass(frozen=True)
class CategoryBreakdownItem:
    category: str
    total: Decimal


@dataclass(frozen=True)
class MonthlyTrendItem:
    year: int
    month: int
    total: Decimal


@dataclass(frozen=True)
class SpendingInsights:
    current_month_total: Decimal
    by_category: list[CategoryBreakdownItem]
    monthly_trend: list[MonthlyTrendItem]


class GetSpendingInsightsHandler:
    def __init__(
        self,
        transaction_repository: TransactionRepository,
        clock: Callable[[], date_type] = date_type.today,
    ) -> None:
        self._transactions = transaction_repository
        # Same DI rationale as GetBudgetOverviewHandler: lets QA Lead pin
        # "today" to a fixed date to test month-boundary behaviour
        # deterministically instead of depending on the real calendar.
        self._clock = clock

    async def handle(self, query: GetSpendingInsightsQuery) -> SpendingInsights:
        today = self._clock()

        month_start, month_end = current_month_bounds(today)
        spend_by_category = await self._transactions.sum_by_category_for_user_in_range(
            query.user_id, month_start, month_end
        )
        by_category = [
            CategoryBreakdownItem(category=category, total=total)
            for category, total in sorted(spend_by_category.items())
        ]
        # Derived from the same query result rather than a second DB
        # call -- current_month_total is exactly the sum of this
        # story's own category breakdown, by definition.
        current_month_total = sum(spend_by_category.values(), Decimal("0"))

        trend_start, trend_end = trailing_months_bounds(today, query.trend_months)
        spend_by_month = await self._transactions.sum_by_month_for_user_in_range(
            query.user_id, trend_start, trend_end
        )
        # Fill every month in range, including zero-spend months, so the
        # trend series has no gaps for the frontend to special-case --
        # same "absent vs. zero" reasoning as get_budget_overview.py,
        # applied the other direction (here we WANT explicit zeros).
        monthly_trend = [
            MonthlyTrendItem(year=y, month=m, total=spend_by_month.get((y, m), Decimal("0")))
            for (y, m) in month_sequence(trend_start, trend_end)
        ]

        return SpendingInsights(
            current_month_total=current_month_total,
            by_category=by_category,
            monthly_trend=monthly_trend,
        )
