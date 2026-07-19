"""Unit tests for the Budget domain model (FINTRACK-20): Budget.new,
Budget.apply_update, and the shared _parse_limit validation. Pure
domain-layer tests -- no DB, no HTTP, no auth. See
tests/integration/test_budgets_api.py for the real-API-level equivalents
and tests/security/test_budgets_security.py for the mandatory security
sweep.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from apps.api.domain.models.budget import Budget, InvalidBudgetAmountError
from apps.api.domain.models.transaction import SuspiciousInputError

# ---------------------------------------------------------------------------
# Budget.new -- category handling
# ---------------------------------------------------------------------------


def test_new_strips_category_whitespace() -> None:
    budget = Budget.new(user_id=uuid.uuid4(), category="  Groceries  ", monthly_limit_raw="500.00")
    assert budget.category == "Groceries"


def test_new_assigns_a_fresh_id_and_matching_timestamps() -> None:
    budget = Budget.new(user_id=uuid.uuid4(), category="Groceries", monthly_limit_raw="500.00")
    assert isinstance(budget.id, uuid.UUID)
    assert budget.created_at == budget.updated_at


def test_new_rejects_empty_category() -> None:
    with pytest.raises(SuspiciousInputError, match="Category is required"):
        Budget.new(user_id=uuid.uuid4(), category="   ", monthly_limit_raw="500.00")


def test_new_rejects_sqli_shaped_category() -> None:
    with pytest.raises(SuspiciousInputError, match="Invalid characters detected"):
        Budget.new(
            user_id=uuid.uuid4(), category="'; DROP TABLE budgets; --", monthly_limit_raw="500.00"
        )


def test_new_rejects_overlong_category() -> None:
    with pytest.raises(SuspiciousInputError, match="too long"):
        Budget.new(user_id=uuid.uuid4(), category="A" * 101, monthly_limit_raw="500.00")


def test_new_accepts_category_at_the_length_boundary() -> None:
    budget = Budget.new(user_id=uuid.uuid4(), category="A" * 100, monthly_limit_raw="500.00")
    assert len(budget.category) == 100


# ---------------------------------------------------------------------------
# Budget.new / _parse_limit -- amount validation (AC2's Gherkin scenario 2
# exactly: "$0" or a negative number)
# ---------------------------------------------------------------------------


def test_new_rejects_zero_limit() -> None:
    with pytest.raises(InvalidBudgetAmountError, match="Budget must be a positive amount"):
        Budget.new(user_id=uuid.uuid4(), category="Dining", monthly_limit_raw="0")


def test_new_rejects_negative_limit() -> None:
    with pytest.raises(InvalidBudgetAmountError, match="Budget must be a positive amount"):
        Budget.new(user_id=uuid.uuid4(), category="Dining", monthly_limit_raw="-50.00")


def test_new_rejects_non_numeric_limit() -> None:
    with pytest.raises(InvalidBudgetAmountError, match="Budget must be a positive amount"):
        Budget.new(user_id=uuid.uuid4(), category="Dining", monthly_limit_raw="not-a-number")


def test_new_rejects_more_than_two_decimal_places() -> None:
    with pytest.raises(InvalidBudgetAmountError, match="at most 2 decimal places"):
        Budget.new(user_id=uuid.uuid4(), category="Dining", monthly_limit_raw="500.123")


def test_new_accepts_two_decimal_places() -> None:
    budget = Budget.new(user_id=uuid.uuid4(), category="Dining", monthly_limit_raw="500.12")
    assert budget.monthly_limit == Decimal("500.12")


def test_new_accepts_whole_number_limit() -> None:
    budget = Budget.new(user_id=uuid.uuid4(), category="Dining", monthly_limit_raw="500")
    assert budget.monthly_limit == Decimal("500")


def test_new_rejects_limit_at_or_above_the_ceiling() -> None:
    with pytest.raises(InvalidBudgetAmountError, match="exceeds maximum allowed limit"):
        Budget.new(user_id=uuid.uuid4(), category="Dining", monthly_limit_raw="999999999.99")


def test_new_accepts_limit_just_below_the_ceiling() -> None:
    budget = Budget.new(user_id=uuid.uuid4(), category="Dining", monthly_limit_raw="999999999.98")
    assert budget.monthly_limit == Decimal("999999999.98")


def test_new_accepts_smallest_positive_limit() -> None:
    budget = Budget.new(user_id=uuid.uuid4(), category="Dining", monthly_limit_raw="0.01")
    assert budget.monthly_limit == Decimal("0.01")


# ---------------------------------------------------------------------------
# Budget.apply_update -- AC4's edit half
# ---------------------------------------------------------------------------


def test_apply_update_changes_the_limit() -> None:
    budget = Budget.new(user_id=uuid.uuid4(), category="Groceries", monthly_limit_raw="500.00")
    budget.apply_update("600.00")
    assert budget.monthly_limit == Decimal("600.00")


def test_apply_update_bumps_updated_at_without_changing_created_at() -> None:
    budget = Budget.new(user_id=uuid.uuid4(), category="Groceries", monthly_limit_raw="500.00")
    original_created_at = budget.created_at
    budget.apply_update("600.00")
    assert budget.created_at == original_created_at
    assert budget.updated_at >= original_created_at


def test_apply_update_does_not_change_id_or_category() -> None:
    budget = Budget.new(user_id=uuid.uuid4(), category="Groceries", monthly_limit_raw="500.00")
    budget_id, category = budget.id, budget.category
    budget.apply_update("600.00")
    assert budget.id == budget_id
    assert budget.category == category


def test_apply_update_rejects_invalid_amount_and_leaves_original_limit_intact() -> None:
    budget = Budget.new(user_id=uuid.uuid4(), category="Groceries", monthly_limit_raw="500.00")
    with pytest.raises(InvalidBudgetAmountError, match="Budget must be a positive amount"):
        budget.apply_update("0")
    assert budget.monthly_limit == Decimal("500.00")


def test_apply_update_rejects_more_than_two_decimal_places() -> None:
    budget = Budget.new(user_id=uuid.uuid4(), category="Groceries", monthly_limit_raw="500.00")
    with pytest.raises(InvalidBudgetAmountError, match="at most 2 decimal places"):
        budget.apply_update("600.999")
