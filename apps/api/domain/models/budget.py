"""Budget domain entity. Story: FINTRACK-20 (Simple Budget Tracking).

A Budget is a single, evergreen monthly spending limit for one category,
scoped per-user (AC1). It deliberately has no "month" field of its own --
"resets each calendar month" (AC3) is implemented by computing spend
on-read, scoped to whatever the current calendar month is, rather than by
persisting a new row (or a batch job resetting a counter) at month
boundaries. See docs/adr/ADR-013-budget-tracking-compute-on-read.md for
the full rationale; this also directly satisfies the story's explicit
out-of-scope line ("no rollover budgets, no multi-month planning") --
there is nothing to roll over or plan across months because a Budget's
limit is just... the limit, always current.

One budget per (user_id, category) -- same "not an append-only history"
shape as FINTRACK-17's CategorisationRule, backed by a unique constraint
at the DB layer (see infrastructure.database.models.BudgetModel).
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from apps.api.domain.models.transaction import SuspiciousInputError


class InvalidBudgetAmountError(ValueError):
    """Raised when a budget limit fails format/range validation. Separate
    from transaction.py's InvalidAmountError because AC2's Gherkin
    scenario requires the exact message "Budget must be a positive
    amount" -- a budget-specific message, not the transaction one."""


# Same SQLi-shaped-pattern defence-in-depth check as transaction.py and
# categorisation_rule.py -- duplicated rather than imported for the same
# reason categorisation_rule.py's is: each domain module owns its own
# validation, this module's is private the way the others are too.
_SQLI_PATTERN = re.compile(
    r"(;|--)\s*\b(drop|delete|truncate|alter|update|insert|exec|union)\b",
    re.IGNORECASE,
)


def _reject_if_suspicious(value: str, field_name: str) -> None:
    if _SQLI_PATTERN.search(value):
        raise SuspiciousInputError("Invalid characters detected")
    if len(value) > 100:
        raise SuspiciousInputError(f"{field_name} is too long")


def _parse_limit(raw: str) -> Decimal:
    try:
        amount = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise InvalidBudgetAmountError("Budget must be a positive amount") from exc

    # AC2's Gherkin is explicit: "$0" is rejected alongside negative
    # numbers, so the check is `<= 0`, not `< 0`.
    if amount <= 0:
        raise InvalidBudgetAmountError("Budget must be a positive amount")

    exponent = amount.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -2:
        raise InvalidBudgetAmountError("Budget must have at most 2 decimal places")

    # Same ceiling as MAX_TRANSACTION_AMOUNT (transaction.py) -- a budget
    # limit is still a currency amount and Numeric(12, 2) is the column
    # type either way; no reason for a budget-specific ceiling.
    if amount >= Decimal("999999999.99"):
        raise InvalidBudgetAmountError("Budget exceeds maximum allowed limit")

    return amount


@dataclass
class Budget:
    """A user's monthly spending limit for one category."""

    id: uuid.UUID
    user_id: uuid.UUID
    category: str
    monthly_limit: Decimal
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @staticmethod
    def new(user_id: uuid.UUID, category: str, monthly_limit_raw: str) -> "Budget":
        category = category.strip()
        if not category:
            raise SuspiciousInputError("Category is required")
        _reject_if_suspicious(category, "Category")

        limit = _parse_limit(monthly_limit_raw)

        now = datetime.now(timezone.utc)
        return Budget(
            id=uuid.uuid4(),
            user_id=user_id,
            category=category,
            monthly_limit=limit,
            created_at=now,
            updated_at=now,
        )

    def apply_update(self, monthly_limit_raw: str) -> None:
        """Edits the limit in place (AC4) -- repository persists the
        result. Category and id are immutable after creation; changing
        the category would really be "delete this budget, create a
        different one," which the API already supports as two calls."""
        self.monthly_limit = _parse_limit(monthly_limit_raw)
        self.updated_at = datetime.now(timezone.utc)
