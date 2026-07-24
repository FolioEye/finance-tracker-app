"""Integration test for
SqlAlchemyTransactionRepository.sum_by_month_for_user_in_range
(FINTRACK-19), run against a real (SQLite, per tests/conftest.py) engine
-- this is the one piece of this story that can't be proven by a unit
test with a fake, since the whole point is the SQL GROUP BY / extract()
construct actually working against a real database.

Uses test_engine/test_session_factory directly rather than the `client`
HTTP fixture -- there's no need to go through the API layer to exercise
one repository method in isolation.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from apps.api.domain.models.transaction import Money, Transaction
from apps.api.infrastructure.repositories.sqlalchemy_transaction_repository import (
    SqlAlchemyTransactionRepository,
)


async def _add_transaction(
    repo: SqlAlchemyTransactionRepository,
    user_id: uuid.UUID,
    amount: str,
    category: str,
    txn_date: date,
) -> None:
    txn = Transaction.new(
        user_id=user_id,
        amount=Money.parse(amount),
        category=category,
        transaction_date=txn_date,
    )
    await repo.add(txn)


@pytest.mark.asyncio
async def test_sum_by_month_groups_and_sums_correctly_across_months(test_session_factory) -> None:
    user_id = uuid.uuid4()
    async with test_session_factory() as session:
        repo = SqlAlchemyTransactionRepository(session)
        await _add_transaction(repo, user_id, "50.00", "Groceries", date(2026, 5, 3))
        await _add_transaction(repo, user_id, "30.00", "Dining", date(2026, 5, 20))
        await _add_transaction(repo, user_id, "100.00", "Groceries", date(2026, 6, 1))
        await _add_transaction(repo, user_id, "999.00", "Groceries", date(2026, 7, 15))  # out of range
        await session.commit()

        totals = await repo.sum_by_month_for_user_in_range(
            user_id, date(2026, 5, 1), date(2026, 7, 1)
        )

    assert totals == {
        (2026, 5): Decimal("80.00"),
        (2026, 6): Decimal("100.00"),
    }
    assert (2026, 7) not in totals  # end_date is exclusive


@pytest.mark.asyncio
async def test_sum_by_month_only_returns_months_with_at_least_one_transaction(
    test_session_factory,
) -> None:
    """Absent-means-zero convention, matching
    sum_by_category_for_user_in_range -- callers wanting a gap-free series
    (GetSpendingInsightsHandler) fill zeros in themselves."""
    user_id = uuid.uuid4()
    async with test_session_factory() as session:
        repo = SqlAlchemyTransactionRepository(session)
        await _add_transaction(repo, user_id, "10.00", "Groceries", date(2026, 5, 3))
        await session.commit()

        totals = await repo.sum_by_month_for_user_in_range(
            user_id, date(2026, 5, 1), date(2026, 8, 1)
        )

    assert totals == {(2026, 5): Decimal("10.00")}
    assert (2026, 6) not in totals
    assert (2026, 7) not in totals


@pytest.mark.asyncio
async def test_sum_by_month_scopes_strictly_by_user_id(test_session_factory) -> None:
    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    async with test_session_factory() as session:
        repo = SqlAlchemyTransactionRepository(session)
        await _add_transaction(repo, user_a, "10.00", "Groceries", date(2026, 7, 5))
        await _add_transaction(repo, user_b, "999.00", "Groceries", date(2026, 7, 5))
        await session.commit()

        totals_a = await repo.sum_by_month_for_user_in_range(
            user_a, date(2026, 7, 1), date(2026, 8, 1)
        )

    assert totals_a == {(2026, 7): Decimal("10.00")}


@pytest.mark.asyncio
async def test_sum_by_month_handles_a_year_boundary_range(test_session_factory) -> None:
    user_id = uuid.uuid4()
    async with test_session_factory() as session:
        repo = SqlAlchemyTransactionRepository(session)
        await _add_transaction(repo, user_id, "40.00", "Groceries", date(2025, 12, 28))
        await _add_transaction(repo, user_id, "60.00", "Groceries", date(2026, 1, 3))
        await session.commit()

        totals = await repo.sum_by_month_for_user_in_range(
            user_id, date(2025, 12, 1), date(2026, 2, 1)
        )

    assert totals == {
        (2025, 12): Decimal("40.00"),
        (2026, 1): Decimal("60.00"),
    }
