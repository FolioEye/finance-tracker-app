"""GetBudgetOverviewQuery + handler -- covers AC2 (progress shown as
actual vs. limit), AC3 (resets each calendar month), and AC5 (categories
with no budget just show spend, no false "over" state). Story: FINTRACK-20.

This is the one place all three of those ACs come together: it merges
the user's persisted Budget rows with a live, current-month spend
aggregate from TransactionRepository. See
docs/adr/ADR-013-budget-tracking-compute-on-read.md for why "resets each
calendar month" is implemented here (compute-on-read) rather than as a
scheduled job or per-month snapshot table.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date as date_type
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable

from apps.api.domain.repositories.budget_repository import BudgetRepository
from apps.api.domain.repositories.transaction_repository import TransactionRepository

_TWO_PLACES = Decimal("0.01")


def _as_percent(spent: Decimal, limit: Decimal) -> Decimal:
    """Quantized to 2dp, half-up. Without this, `spent / limit * 100` on
    two arbitrary currency Decimals produces an inconsistent number of
    digits depending on the inputs -- "60.0" for 300/500, but a long
    near-repeating value for something like 100/300 -- which is a poor
    contract for API consumers rendering a percentage. Found by a Tech
    Lead smoke test before handoff (300/500 rendered "60.0", not "60.00").
    """
    return (spent / limit * Decimal("100")).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def _current_month_bounds(today: date_type) -> tuple[date_type, date_type]:
    """[start, end) -- start is the 1st of the current month, end is the
    1st of the following month (exclusive), so a plain `>= start, < end`
    range filter naturally excludes both last month's and next month's
    transactions with no special-casing for month length or year rollover.
    """
    start = today.replace(day=1)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


@dataclass(frozen=True)
class GetBudgetOverviewQuery:
    user_id: uuid.UUID


@dataclass(frozen=True)
class BudgetOverviewItem:
    """One row of the overview -- either a budgeted category (budget_id
    and monthly_limit set, percent_used computed) or an unbudgeted
    category with activity this month (budget_id and monthly_limit are
    None, percent_used is None -- AC5's "no false over state": the
    frontend has nothing to compute a percentage or an over/under
    judgement against, so this shape makes rendering a false indicator
    structurally awkward rather than just "unlikely").
    """

    budget_id: uuid.UUID | None
    category: str
    monthly_limit: Decimal | None
    spent: Decimal
    percent_used: Decimal | None
    is_over_budget: bool


class GetBudgetOverviewHandler:
    def __init__(
        self,
        budget_repository: BudgetRepository,
        transaction_repository: TransactionRepository,
        clock: Callable[[], date_type] = date_type.today,
    ) -> None:
        self._budgets = budget_repository
        self._transactions = transaction_repository
        # Injected rather than calling date.today() directly inline below
        # -- lets QA Lead's tests pin "today" to a fixed date to exercise
        # AC3 (month-boundary/reset behaviour) deterministically, same DI
        # rationale the constraint matrix applies to every other
        # environment-dependent dependency in this codebase.
        self._clock = clock

    async def handle(self, query: GetBudgetOverviewQuery) -> list[BudgetOverviewItem]:
        start, end = _current_month_bounds(self._clock())

        budgets = await self._budgets.list_for_user(query.user_id)
        spend_by_category = await self._transactions.sum_by_category_for_user_in_range(
            query.user_id, start, end
        )

        items: list[BudgetOverviewItem] = []
        budgeted_categories: set[str] = set()

        for budget in budgets:
            spent = spend_by_category.get(budget.category, Decimal("0"))
            percent_used = (
                _as_percent(spent, budget.monthly_limit) if budget.monthly_limit else Decimal("0.00")
            )
            items.append(
                BudgetOverviewItem(
                    budget_id=budget.id,
                    category=budget.category,
                    monthly_limit=budget.monthly_limit,
                    spent=spent,
                    percent_used=percent_used,
                    is_over_budget=spent > budget.monthly_limit,
                )
            )
            budgeted_categories.add(budget.category)

        # AC5: a category with spend this month but no budget shows spend
        # only -- never a percent_used or is_over_budget value.
        for category, spent in spend_by_category.items():
            if category in budgeted_categories:
                continue
            items.append(
                BudgetOverviewItem(
                    budget_id=None,
                    category=category,
                    monthly_limit=None,
                    spent=spent,
                    percent_used=None,
                    is_over_budget=False,
                )
            )

        return items
