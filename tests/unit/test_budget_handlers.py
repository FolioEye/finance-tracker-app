"""Unit tests for the budget command handlers (CreateBudgetHandler,
UpdateBudgetHandler, DeleteBudgetHandler) and GetBudgetOverviewHandler
(FINTRACK-20). Fake in-memory repositories stand in for the real
SQLAlchemy adapters, same pattern as
tests/unit/test_categorisation_rule_handlers.py's
FakeCategorisationRuleRepository.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from apps.api.application.commands.create_budget import (
    CreateBudgetCommand,
    CreateBudgetHandler,
)
from apps.api.application.commands.delete_budget import (
    DeleteBudgetCommand,
    DeleteBudgetHandler,
)
from apps.api.application.commands.update_budget import (
    UpdateBudgetCommand,
    UpdateBudgetHandler,
)
from apps.api.application.queries.get_budget_overview import (
    GetBudgetOverviewHandler,
    GetBudgetOverviewQuery,
)
from apps.api.domain.models.budget import Budget, InvalidBudgetAmountError
from apps.api.domain.models.transaction import SuspiciousInputError
from apps.api.domain.repositories.budget_repository import (
    BudgetAlreadyExistsError,
    BudgetNotFoundError,
)


class FakeBudgetRepository:
    """In-memory stand-in for SqlAlchemyBudgetRepository. Implements the
    full BudgetRepository port, including its documented
    None-for-not-found-or-not-yours semantics on get_by_id_for_user.
    """

    def __init__(self) -> None:
        self.budgets: dict[uuid.UUID, Budget] = {}

    async def add(self, budget: Budget) -> None:
        self.budgets[budget.id] = budget

    async def get_by_id_for_user(self, budget_id: uuid.UUID, user_id: uuid.UUID):
        budget = self.budgets.get(budget_id)
        if budget is None or budget.user_id != user_id:
            return None
        return budget

    async def get_by_category_for_user(self, user_id: uuid.UUID, category: str):
        for budget in self.budgets.values():
            if budget.user_id == user_id and budget.category == category:
                return budget
        return None

    async def list_for_user(self, user_id: uuid.UUID) -> list[Budget]:
        return [b for b in self.budgets.values() if b.user_id == user_id]

    async def update(self, budget: Budget) -> None:
        self.budgets[budget.id] = budget

    async def delete(self, budget_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        budget = self.budgets.get(budget_id)
        if budget is None or budget.user_id != user_id:
            return False
        del self.budgets[budget_id]
        return True


class FakeTransactionRepository:
    """Only implements the one method GetBudgetOverviewHandler actually
    calls -- sum_by_category_for_user_in_range. Backed by a flat list of
    (user_id, category, amount, txn_date) tuples so tests can seed
    transactions across different months without a real DB.
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
            if row_user_id != user_id:
                continue
            if not (start_date <= txn_date < end_date):
                continue
            totals[category] = totals.get(category, Decimal("0")) + amount
        return totals


@pytest.fixture
def budgets() -> FakeBudgetRepository:
    return FakeBudgetRepository()


@pytest.fixture
def transactions() -> FakeTransactionRepository:
    return FakeTransactionRepository()


# ---------------------------------------------------------------------------
# CreateBudgetHandler -- AC1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_budget_creates_a_new_budget(budgets: FakeBudgetRepository) -> None:
    handler = CreateBudgetHandler(budget_repository=budgets)
    user_id = uuid.uuid4()
    budget = await handler.handle(
        CreateBudgetCommand(user_id=user_id, category="Groceries", monthly_limit="500.00")
    )
    assert budget.category == "Groceries"
    assert budget.monthly_limit == Decimal("500.00")
    assert len(await budgets.list_for_user(user_id)) == 1


@pytest.mark.asyncio
async def test_create_budget_rejects_a_duplicate_category(budgets: FakeBudgetRepository) -> None:
    handler = CreateBudgetHandler(budget_repository=budgets)
    user_id = uuid.uuid4()
    await handler.handle(
        CreateBudgetCommand(user_id=user_id, category="Groceries", monthly_limit="500.00")
    )
    with pytest.raises(BudgetAlreadyExistsError):
        await handler.handle(
            CreateBudgetCommand(user_id=user_id, category="Groceries", monthly_limit="600.00")
        )
    assert len(await budgets.list_for_user(user_id)) == 1


@pytest.mark.asyncio
async def test_create_budget_rejects_invalid_amount_before_touching_the_repository(
    budgets: FakeBudgetRepository,
) -> None:
    handler = CreateBudgetHandler(budget_repository=budgets)
    user_id = uuid.uuid4()
    with pytest.raises(InvalidBudgetAmountError, match="Budget must be a positive amount"):
        await handler.handle(CreateBudgetCommand(user_id=user_id, category="Dining", monthly_limit="0"))
    assert await budgets.list_for_user(user_id) == []


@pytest.mark.asyncio
async def test_create_budget_rejects_sqli_shaped_category(budgets: FakeBudgetRepository) -> None:
    handler = CreateBudgetHandler(budget_repository=budgets)
    user_id = uuid.uuid4()
    with pytest.raises(SuspiciousInputError, match="Invalid characters detected"):
        await handler.handle(
            CreateBudgetCommand(
                user_id=user_id, category="'; DROP TABLE budgets; --", monthly_limit="500.00"
            )
        )
    assert await budgets.list_for_user(user_id) == []


@pytest.mark.asyncio
async def test_create_budget_scopes_budgets_per_user(budgets: FakeBudgetRepository) -> None:
    handler = CreateBudgetHandler(budget_repository=budgets)
    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    await handler.handle(CreateBudgetCommand(user_id=user_a, category="Groceries", monthly_limit="500.00"))
    await handler.handle(CreateBudgetCommand(user_id=user_b, category="Groceries", monthly_limit="300.00"))
    assert len(await budgets.list_for_user(user_a)) == 1
    assert len(await budgets.list_for_user(user_b)) == 1


# ---------------------------------------------------------------------------
# UpdateBudgetHandler -- AC4 edit half
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_budget_changes_the_limit(budgets: FakeBudgetRepository) -> None:
    create_handler = CreateBudgetHandler(budget_repository=budgets)
    user_id = uuid.uuid4()
    budget = await create_handler.handle(
        CreateBudgetCommand(user_id=user_id, category="Groceries", monthly_limit="500.00")
    )
    update_handler = UpdateBudgetHandler(budget_repository=budgets)
    updated = await update_handler.handle(
        UpdateBudgetCommand(budget_id=budget.id, user_id=user_id, monthly_limit="600.00")
    )
    assert updated.monthly_limit == Decimal("600.00")


@pytest.mark.asyncio
async def test_update_budget_raises_not_found_for_a_nonexistent_id(budgets: FakeBudgetRepository) -> None:
    handler = UpdateBudgetHandler(budget_repository=budgets)
    with pytest.raises(BudgetNotFoundError):
        await handler.handle(
            UpdateBudgetCommand(budget_id=uuid.uuid4(), user_id=uuid.uuid4(), monthly_limit="600.00")
        )


@pytest.mark.asyncio
async def test_update_budget_raises_not_found_for_another_users_budget(
    budgets: FakeBudgetRepository,
) -> None:
    """IDOR at the handler layer -- the attacker gets the same
    BudgetNotFoundError as a truly nonexistent id, never a distinct
    "forbidden" signal."""
    create_handler = CreateBudgetHandler(budget_repository=budgets)
    owner_id = uuid.uuid4()
    budget = await create_handler.handle(
        CreateBudgetCommand(user_id=owner_id, category="Private", monthly_limit="100.00")
    )
    update_handler = UpdateBudgetHandler(budget_repository=budgets)
    attacker_id = uuid.uuid4()
    with pytest.raises(BudgetNotFoundError):
        await update_handler.handle(
            UpdateBudgetCommand(budget_id=budget.id, user_id=attacker_id, monthly_limit="1.00")
        )
    # The owner's budget is untouched.
    still_theirs = await budgets.get_by_id_for_user(budget.id, owner_id)
    assert still_theirs.monthly_limit == Decimal("100.00")


@pytest.mark.asyncio
async def test_update_budget_rejects_invalid_amount(budgets: FakeBudgetRepository) -> None:
    create_handler = CreateBudgetHandler(budget_repository=budgets)
    user_id = uuid.uuid4()
    budget = await create_handler.handle(
        CreateBudgetCommand(user_id=user_id, category="Groceries", monthly_limit="500.00")
    )
    update_handler = UpdateBudgetHandler(budget_repository=budgets)
    with pytest.raises(InvalidBudgetAmountError):
        await update_handler.handle(
            UpdateBudgetCommand(budget_id=budget.id, user_id=user_id, monthly_limit="-1.00")
        )


# ---------------------------------------------------------------------------
# DeleteBudgetHandler -- AC4 remove half
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_budget_removes_it(budgets: FakeBudgetRepository) -> None:
    create_handler = CreateBudgetHandler(budget_repository=budgets)
    user_id = uuid.uuid4()
    budget = await create_handler.handle(
        CreateBudgetCommand(user_id=user_id, category="Groceries", monthly_limit="500.00")
    )
    delete_handler = DeleteBudgetHandler(budget_repository=budgets)
    await delete_handler.handle(DeleteBudgetCommand(budget_id=budget.id, user_id=user_id))
    assert await budgets.list_for_user(user_id) == []


@pytest.mark.asyncio
async def test_delete_budget_raises_not_found_for_another_users_budget(
    budgets: FakeBudgetRepository,
) -> None:
    create_handler = CreateBudgetHandler(budget_repository=budgets)
    owner_id = uuid.uuid4()
    budget = await create_handler.handle(
        CreateBudgetCommand(user_id=owner_id, category="Private", monthly_limit="100.00")
    )
    delete_handler = DeleteBudgetHandler(budget_repository=budgets)
    with pytest.raises(BudgetNotFoundError):
        await delete_handler.handle(
            DeleteBudgetCommand(budget_id=budget.id, user_id=uuid.uuid4())
        )
    assert len(await budgets.list_for_user(owner_id)) == 1


@pytest.mark.asyncio
async def test_delete_budget_twice_raises_not_found_the_second_time(
    budgets: FakeBudgetRepository,
) -> None:
    create_handler = CreateBudgetHandler(budget_repository=budgets)
    user_id = uuid.uuid4()
    budget = await create_handler.handle(
        CreateBudgetCommand(user_id=user_id, category="Groceries", monthly_limit="500.00")
    )
    delete_handler = DeleteBudgetHandler(budget_repository=budgets)
    await delete_handler.handle(DeleteBudgetCommand(budget_id=budget.id, user_id=user_id))
    with pytest.raises(BudgetNotFoundError):
        await delete_handler.handle(DeleteBudgetCommand(budget_id=budget.id, user_id=user_id))


# ---------------------------------------------------------------------------
# GetBudgetOverviewHandler -- AC2 (progress vs. limit), AC3 (monthly
# reset), AC5 (no false "over" state for unbudgeted categories)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_overview_computes_percent_used_for_a_budgeted_category(
    budgets: FakeBudgetRepository, transactions: FakeTransactionRepository
) -> None:
    """Matches the BA's Gherkin scenario 1 exactly: $300 spent against a
    $500 budget shows 60% used. Also the exact case the Tech Lead's own
    smoke test caught unquantized ("60.0" instead of "60.00") -- asserted
    here as a string to lock the fix in."""
    user_id = uuid.uuid4()
    create_handler = CreateBudgetHandler(budget_repository=budgets)
    await create_handler.handle(
        CreateBudgetCommand(user_id=user_id, category="Groceries", monthly_limit="500.00")
    )
    transactions.seed(user_id, "Groceries", "300.00", date(2026, 7, 15))

    handler = GetBudgetOverviewHandler(
        budget_repository=budgets, transaction_repository=transactions, clock=lambda: date(2026, 7, 19)
    )
    items = await handler.handle(GetBudgetOverviewQuery(user_id=user_id))
    groceries = next(i for i in items if i.category == "Groceries")
    assert groceries.spent == Decimal("300.00")
    assert str(groceries.percent_used) == "60.00"
    assert groceries.is_over_budget is False


@pytest.mark.asyncio
async def test_overview_flags_over_budget_with_uncapped_percentage(
    budgets: FakeBudgetRepository, transactions: FakeTransactionRepository
) -> None:
    """Matches the BA's Gherkin scenario 3 exactly: $250 spent against a
    $200 budget is over budget, and the overage is visible (125%), not
    silently capped at 100%."""
    user_id = uuid.uuid4()
    create_handler = CreateBudgetHandler(budget_repository=budgets)
    await create_handler.handle(
        CreateBudgetCommand(user_id=user_id, category="Entertainment", monthly_limit="200.00")
    )
    transactions.seed(user_id, "Entertainment", "250.00", date(2026, 7, 10))

    handler = GetBudgetOverviewHandler(
        budget_repository=budgets, transaction_repository=transactions, clock=lambda: date(2026, 7, 19)
    )
    items = await handler.handle(GetBudgetOverviewQuery(user_id=user_id))
    entertainment = next(i for i in items if i.category == "Entertainment")
    assert entertainment.is_over_budget is True
    assert str(entertainment.percent_used) == "125.00"


@pytest.mark.asyncio
async def test_overview_shows_spend_only_for_a_category_with_no_budget(
    budgets: FakeBudgetRepository, transactions: FakeTransactionRepository
) -> None:
    """Matches the BA's Gherkin scenario 8 (AC5) exactly: no budget_id,
    no monthly_limit, no percent_used -- just spend."""
    user_id = uuid.uuid4()
    transactions.seed(user_id, "Entertainment", "120.00", date(2026, 7, 10))

    handler = GetBudgetOverviewHandler(
        budget_repository=budgets, transaction_repository=transactions, clock=lambda: date(2026, 7, 19)
    )
    items = await handler.handle(GetBudgetOverviewQuery(user_id=user_id))
    entertainment = next(i for i in items if i.category == "Entertainment")
    assert entertainment.budget_id is None
    assert entertainment.monthly_limit is None
    assert entertainment.spent == Decimal("120.00")
    assert entertainment.percent_used is None
    assert entertainment.is_over_budget is False


@pytest.mark.asyncio
async def test_overview_excludes_prior_month_spend_from_the_current_months_total(
    budgets: FakeBudgetRepository, transactions: FakeTransactionRepository
) -> None:
    """Matches the BA's Gherkin scenario 5 (AC3) exactly: last month's
    spend does not carry into this month's total. Unit-level equivalent of
    the API-level test in test_budgets_api.py -- this one runs against
    the handler directly via the injected clock, no HTTP/DB round trip."""
    user_id = uuid.uuid4()
    create_handler = CreateBudgetHandler(budget_repository=budgets)
    await create_handler.handle(
        CreateBudgetCommand(user_id=user_id, category="Groceries", monthly_limit="500.00")
    )
    transactions.seed(user_id, "Groceries", "450.00", date(2026, 6, 15))  # last month
    transactions.seed(user_id, "Groceries", "100.00", date(2026, 7, 10))  # this month

    handler = GetBudgetOverviewHandler(
        budget_repository=budgets, transaction_repository=transactions, clock=lambda: date(2026, 7, 19)
    )
    items = await handler.handle(GetBudgetOverviewQuery(user_id=user_id))
    groceries = next(i for i in items if i.category == "Groceries")
    assert groceries.spent == Decimal("100.00")
    assert str(groceries.percent_used) == "20.00"


@pytest.mark.asyncio
async def test_overview_handles_the_december_to_january_year_rollover(
    budgets: FakeBudgetRepository, transactions: FakeTransactionRepository
) -> None:
    """Edge case for _current_month_bounds: "today" in December must not
    leak January-of-next-year spend, and a January transaction from the
    same day last year must not leak in either."""
    user_id = uuid.uuid4()
    create_handler = CreateBudgetHandler(budget_repository=budgets)
    await create_handler.handle(
        CreateBudgetCommand(user_id=user_id, category="Groceries", monthly_limit="500.00")
    )
    transactions.seed(user_id, "Groceries", "50.00", date(2025, 12, 20))  # this Dec
    transactions.seed(user_id, "Groceries", "999.00", date(2026, 1, 5))  # next Jan -- must be excluded

    handler = GetBudgetOverviewHandler(
        budget_repository=budgets, transaction_repository=transactions, clock=lambda: date(2025, 12, 25)
    )
    items = await handler.handle(GetBudgetOverviewQuery(user_id=user_id))
    groceries = next(i for i in items if i.category == "Groceries")
    assert groceries.spent == Decimal("50.00")


@pytest.mark.asyncio
async def test_overview_shows_zero_percent_for_a_budget_with_no_spend_yet(
    budgets: FakeBudgetRepository, transactions: FakeTransactionRepository
) -> None:
    user_id = uuid.uuid4()
    create_handler = CreateBudgetHandler(budget_repository=budgets)
    await create_handler.handle(
        CreateBudgetCommand(user_id=user_id, category="Groceries", monthly_limit="500.00")
    )
    handler = GetBudgetOverviewHandler(
        budget_repository=budgets, transaction_repository=transactions, clock=lambda: date(2026, 7, 19)
    )
    items = await handler.handle(GetBudgetOverviewQuery(user_id=user_id))
    groceries = next(i for i in items if i.category == "Groceries")
    assert groceries.spent == Decimal("0")
    assert str(groceries.percent_used) == "0.00"
    assert groceries.is_over_budget is False


@pytest.mark.asyncio
async def test_overview_only_returns_the_requesting_users_budgets_and_spend(
    budgets: FakeBudgetRepository, transactions: FakeTransactionRepository
) -> None:
    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    create_handler = CreateBudgetHandler(budget_repository=budgets)
    await create_handler.handle(
        CreateBudgetCommand(user_id=user_a, category="Groceries", monthly_limit="500.00")
    )
    await create_handler.handle(
        CreateBudgetCommand(user_id=user_b, category="Groceries", monthly_limit="300.00")
    )
    transactions.seed(user_a, "Groceries", "100.00", date(2026, 7, 10))
    transactions.seed(user_b, "Groceries", "999.00", date(2026, 7, 10))

    handler = GetBudgetOverviewHandler(
        budget_repository=budgets, transaction_repository=transactions, clock=lambda: date(2026, 7, 19)
    )
    items_a = await handler.handle(GetBudgetOverviewQuery(user_id=user_a))
    groceries_a = next(i for i in items_a if i.category == "Groceries")
    assert groceries_a.spent == Decimal("100.00")
    assert groceries_a.monthly_limit == Decimal("500.00")
