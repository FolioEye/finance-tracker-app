"""Unit tests for the Transaction domain model (Money value object,
Transaction entity). Pure domain-layer tests -- no DB, no HTTP, no auth.
See tests/integration/test_transactions_api.py for the real-API-level
equivalents and tests/security/test_transactions_security.py for the
mandatory security sweep.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from apps.api.domain.models.transaction import (
    MAX_TRANSACTION_AMOUNT,
    AmountExceedsMaximumError,
    InvalidAmountError,
    Money,
    SuspiciousInputError,
    Transaction,
)

# ---------------------------------------------------------------------------
# Money.parse -- AC1 ("positive decimal amount, 2dp max")
# ---------------------------------------------------------------------------


def test_money_parse_accepts_valid_two_decimal_amount() -> None:
    """Matches Gherkin happy path: amount "42.50"."""
    money = Money.parse("42.50")
    assert str(money) == "42.50"


def test_money_parse_accepts_whole_number_amount() -> None:
    money = Money.parse("100")
    assert str(money) == "100"


def test_money_parse_rejects_negative_amount() -> None:
    """Matches Gherkin: amount "-15.00" -> 'Amount must be a positive number'."""
    with pytest.raises(InvalidAmountError, match="Amount must be a positive number"):
        Money.parse("-15.00")


def test_money_parse_rejects_zero() -> None:
    with pytest.raises(InvalidAmountError, match="Amount must be a positive number"):
        Money.parse("0")
    with pytest.raises(InvalidAmountError, match="Amount must be a positive number"):
        Money.parse("0.00")


def test_money_parse_rejects_non_numeric_string() -> None:
    with pytest.raises(InvalidAmountError, match="Amount must be a valid number"):
        Money.parse("not-a-number")


def test_money_parse_rejects_empty_string() -> None:
    with pytest.raises(InvalidAmountError, match="Amount must be a valid number"):
        Money.parse("")


def test_money_parse_rejects_more_than_two_decimal_places() -> None:
    with pytest.raises(InvalidAmountError, match="at most 2 decimal places"):
        Money.parse("10.999")


def test_money_parse_accepts_exactly_two_decimal_places() -> None:
    money = Money.parse("10.99")
    assert str(money) == "10.99"


def test_money_parse_rejects_amount_at_the_maximum_boundary_exactly() -> None:
    """Matches Gherkin exactly: "999999999.99" -> 'Amount exceeds maximum
    allowed limit'. This is a >= check, not a >, so the boundary value
    itself is rejected, not just values above it.
    """
    with pytest.raises(AmountExceedsMaximumError, match="Amount exceeds maximum allowed limit"):
        Money.parse("999999999.99")


def test_money_parse_rejects_amount_above_the_maximum() -> None:
    with pytest.raises(AmountExceedsMaximumError):
        Money.parse("1000000000.00")


def test_money_parse_accepts_amount_one_cent_below_the_maximum() -> None:
    money = Money.parse("999999999.98")
    assert money.value < MAX_TRANSACTION_AMOUNT


def test_money_str_round_trips_the_original_decimal_representation() -> None:
    """Money is Decimal-backed specifically so this doesn't drift the way
    a float round-trip could (e.g. 42.50 -> 42.5 -> "42.5", which would be
    a real behavioural difference a user would notice)."""
    assert str(Money.parse("42.50")) == "42.50"
    assert str(Money.parse("0.01")) == "0.01"


# ---------------------------------------------------------------------------
# Transaction.new -- category/note validation, AC2/AC3/AC6
# ---------------------------------------------------------------------------


def _amount(raw: str = "42.50") -> Money:
    return Money.parse(raw)


def test_transaction_new_creates_a_valid_transaction() -> None:
    user_id = uuid.uuid4()
    txn = Transaction.new(
        user_id=user_id,
        amount=_amount(),
        category="Groceries",
        transaction_date=date(2026, 7, 2),
        note="Weekly shop",
    )
    assert txn.user_id == user_id
    assert txn.category == "Groceries"
    assert txn.note == "Weekly shop"
    assert isinstance(txn.id, uuid.UUID)
    assert txn.created_at == txn.updated_at


def test_transaction_new_rejects_empty_category() -> None:
    with pytest.raises(InvalidAmountError, match="Category is required"):
        Transaction.new(
            user_id=uuid.uuid4(),
            amount=_amount(),
            category="   ",
            transaction_date=date(2026, 7, 2),
        )


def test_transaction_new_strips_whitespace_from_category_and_note() -> None:
    txn = Transaction.new(
        user_id=uuid.uuid4(),
        amount=_amount(),
        category="  Groceries  ",
        transaction_date=date(2026, 7, 2),
        note="  Weekly shop  ",
    )
    assert txn.category == "Groceries"
    assert txn.note == "Weekly shop"


def test_transaction_new_treats_blank_note_as_none() -> None:
    txn = Transaction.new(
        user_id=uuid.uuid4(),
        amount=_amount(),
        category="Groceries",
        transaction_date=date(2026, 7, 2),
        note="   ",
    )
    assert txn.note is None


def test_transaction_new_allows_custom_category_per_ac2() -> None:
    """AC2: 'Required category, custom allowed' -- any non-empty,
    non-suspicious string is accepted, not just a fixed enum."""
    txn = Transaction.new(
        user_id=uuid.uuid4(),
        amount=_amount(),
        category="My Custom Side-Hustle Fund",
        transaction_date=date(2026, 7, 2),
    )
    assert txn.category == "My Custom Side-Hustle Fund"


def test_transaction_new_rejects_sql_injection_shaped_category() -> None:
    """Matches Gherkin: SQL injection in transaction description ->
    'Invalid characters detected'. Category is the other free-text field
    the same pattern applies to."""
    with pytest.raises(SuspiciousInputError, match="Invalid characters detected"):
        Transaction.new(
            user_id=uuid.uuid4(),
            amount=_amount(),
            category="'; DROP TABLE transactions; --",
            transaction_date=date(2026, 7, 2),
        )


def test_transaction_new_rejects_sql_injection_shaped_note() -> None:
    with pytest.raises(SuspiciousInputError, match="Invalid characters detected"):
        Transaction.new(
            user_id=uuid.uuid4(),
            amount=_amount(),
            category="Groceries",
            transaction_date=date(2026, 7, 2),
            note="'; DROP TABLE transactions; --",
        )


def test_transaction_new_does_not_false_positive_on_apostrophes_in_legitimate_text() -> None:
    """The SQLi pattern is deliberately narrow (statement terminator/comment
    marker + destructive keyword) so ordinary merchant names with
    apostrophes aren't rejected -- per ADR-010's explicit design note."""
    txn = Transaction.new(
        user_id=uuid.uuid4(),
        amount=_amount(),
        category="O'Brien's Cafe",
        transaction_date=date(2026, 7, 2),
        note="Client's lunch -- won't happen again",
    )
    assert txn.category == "O'Brien's Cafe"
    assert txn.note == "Client's lunch -- won't happen again"


def test_transaction_new_rejects_overlong_note() -> None:
    with pytest.raises(SuspiciousInputError, match="too long"):
        Transaction.new(
            user_id=uuid.uuid4(),
            amount=_amount(),
            category="Groceries",
            transaction_date=date(2026, 7, 2),
            note="x" * 501,
        )


# ---------------------------------------------------------------------------
# Transaction.apply_update -- AC5 ("Editable/deletable"), no Gherkin coverage
# (flagged by Tech Lead in ADR-010) -- these are the QA Lead's gap-fill tests.
# ---------------------------------------------------------------------------


def test_apply_update_changes_only_the_provided_fields() -> None:
    txn = Transaction.new(
        user_id=uuid.uuid4(),
        amount=_amount("42.50"),
        category="Groceries",
        transaction_date=date(2026, 7, 2),
        note="Weekly shop",
    )
    original_created_at = txn.created_at

    txn.apply_update(amount=Money.parse("55.00"))

    assert str(txn.amount) == "55.00"
    assert txn.category == "Groceries"  # unchanged
    assert txn.note == "Weekly shop"  # unchanged
    assert txn.created_at == original_created_at  # never mutated
    assert txn.updated_at >= original_created_at


def test_apply_update_can_clear_a_note_by_passing_empty_string() -> None:
    txn = Transaction.new(
        user_id=uuid.uuid4(),
        amount=_amount(),
        category="Groceries",
        transaction_date=date(2026, 7, 2),
        note="Weekly shop",
    )
    txn.apply_update(note="")
    assert txn.note is None


def test_apply_update_rejects_sql_injection_shaped_category_on_update() -> None:
    txn = Transaction.new(
        user_id=uuid.uuid4(),
        amount=_amount(),
        category="Groceries",
        transaction_date=date(2026, 7, 2),
    )
    with pytest.raises(SuspiciousInputError, match="Invalid characters detected"):
        txn.apply_update(category="'; DROP TABLE transactions; --")


def test_apply_update_rejects_empty_category_on_update() -> None:
    txn = Transaction.new(
        user_id=uuid.uuid4(),
        amount=_amount(),
        category="Groceries",
        transaction_date=date(2026, 7, 2),
    )
    with pytest.raises(InvalidAmountError, match="Category is required"):
        txn.apply_update(category="   ")
