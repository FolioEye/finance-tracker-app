"""Transaction domain entity. Story: FINTRACK-15 (Add Manual Transaction).

Per the PM's architecture constraint (see the FinTrack business case, epic
EP-02): manual entry, CSV import (FINTRACK-16), and receipt OCR (P1) are
all meant to produce the same CreateTransactionCommand shape -- this
module and application/commands/create_transaction.py are written with
that shared shape in mind, even though only manual entry calls it today.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


class InvalidAmountError(ValueError):
    """Raised when an amount fails format/range validation."""


class AmountExceedsMaximumError(ValueError):
    """Raised when an amount is at or above the hard ceiling."""


class SuspiciousInputError(ValueError):
    """Raised when a free-text field matches a SQL-injection-shaped
    pattern. Note: parameterised queries (via SQLAlchemy's query builder,
    used everywhere in this codebase) are the actual defence against SQL
    injection -- this check is defence-in-depth plus an explicit UX
    requirement from FINTRACK-15's Gherkin ("the input should be
    sanitised" + a specific validation error + a logged security event),
    not a substitute for parameterisation. A keyword/pattern blocklist is
    inherently bypassable and must never be relied on as the sole
    safeguard.
    """


# Hard ceiling matching the Gherkin's exact rejected boundary value
# (999999999.99 must be rejected) -- see docs/adr/ADR-010-transaction-amount-validation.md.
MAX_TRANSACTION_AMOUNT = Decimal("999999999.99")

# Deliberately conservative and easy to reason about, not an attempt at a
# complete SQL grammar parser. Looks for the combination of a statement
# terminator/comment marker with a destructive keyword, which is the
# specific shape FINTRACK-13/14/15's Gherkin scenarios all use
# ("'; DROP TABLE ...; --"). A merchant name containing an apostrophe
# alone (e.g. "O'Brien's Cafe") does NOT match this pattern and is not
# rejected.
_SQLI_PATTERN = re.compile(
    r"(;|--)\s*\b(drop|delete|truncate|alter|update|insert|exec|union)\b",
    re.IGNORECASE,
)


def _reject_if_suspicious(value: str, field_name: str) -> None:
    if _SQLI_PATTERN.search(value):
        raise SuspiciousInputError("Invalid characters detected")
    if len(value) > 500:
        raise SuspiciousInputError(f"{field_name} is too long")


@dataclass(frozen=True)
class Money:
    """Value object -- a validated transaction amount.

    Decimal only, never float: binary floating point cannot represent
    most currency values exactly (e.g. 0.1 + 0.2 != 0.3), which is
    unacceptable for money. Accepts the raw string as typed by the user
    (same rationale as Email/LoginRequest elsewhere in this codebase --
    validation and user-facing error messages live in the domain layer,
    not at the Pydantic boundary).
    """

    value: Decimal

    @staticmethod
    def parse(raw: str) -> "Money":
        try:
            amount = Decimal(raw)
        except (InvalidOperation, ValueError) as exc:
            raise InvalidAmountError("Amount must be a valid number") from exc

        if amount <= 0:
            raise InvalidAmountError("Amount must be a positive number")

        # exponent > -1 means 0 decimal places; -2 means exactly 2; more
        # negative (e.g. -3) means more than 2 decimal places, which is
        # rejected per AC1 ("2dp max").
        exponent = amount.as_tuple().exponent
        if isinstance(exponent, int) and exponent < -2:
            raise InvalidAmountError("Amount must have at most 2 decimal places")

        if amount >= MAX_TRANSACTION_AMOUNT:
            raise AmountExceedsMaximumError("Amount exceeds maximum allowed limit")

        return Money(value=amount)

    def __str__(self) -> str:
        return str(self.value)


@dataclass
class Transaction:
    """A single manually-entered (or, in future, imported) transaction.

    Deliberately scoped to user_id -- every repository query filters on
    this, never trusting a client-supplied user identifier, per the
    project's IDOR-prevention discipline (see FINTRACK-19/20's Gherkin for
    the same pattern applied to dashboard/budget data).
    """

    id: uuid.UUID
    user_id: uuid.UUID
    amount: Money
    category: str
    transaction_date: date_type
    note: str | None = None
    entry_source: str = "manual"  # "manual" | "csv_import" (FINTRACK-16) | "receipt_ocr" (P1)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @staticmethod
    def new(
        user_id: uuid.UUID,
        amount: Money,
        category: str,
        transaction_date: date_type,
        note: str | None = None,
        entry_source: str = "manual",
    ) -> "Transaction":
        category = category.strip()
        if not category:
            raise InvalidAmountError("Category is required")
        _reject_if_suspicious(category, "Category")
        if note:
            note = note.strip()
            _reject_if_suspicious(note, "Note")

        now = datetime.now(timezone.utc)
        return Transaction(
            id=uuid.uuid4(),
            user_id=user_id,
            amount=amount,
            category=category,
            transaction_date=transaction_date,
            note=note or None,
            entry_source=entry_source,
            created_at=now,
            updated_at=now,
        )

    def apply_update(
        self,
        amount: Money | None = None,
        category: str | None = None,
        transaction_date: date_type | None = None,
        note: str | None = None,
    ) -> None:
        """Mutates in place -- the repository is responsible for persisting
        the result. Only provided fields are changed (partial update)."""
        if amount is not None:
            self.amount = amount
        if category is not None:
            category = category.strip()
            if not category:
                raise InvalidAmountError("Category is required")
            _reject_if_suspicious(category, "Category")
            self.category = category
        if transaction_date is not None:
            self.transaction_date = transaction_date
        if note is not None:
            note = note.strip()
            if note:
                _reject_if_suspicious(note, "Note")
            self.note = note or None
        self.updated_at = datetime.now(timezone.utc)
