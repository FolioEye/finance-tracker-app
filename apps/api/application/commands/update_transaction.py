"""UpdateTransactionCommand + handler -- covers AC5 ("Editable/deletable").

Not covered by any of the BA's 4 Gherkin scenarios for FINTRACK-15 (all
four are create-only) -- implemented anyway since AC5 explicitly requires
it. Flagged to QA Lead: this handler has no Gherkin-mapped test yet.

FINTRACK-17 (AC3, Gherkin scenario 5) extends this handler with the
correction-feedback loop: correcting an imported transaction's category
away from "Uncategorised" creates/updates a personal CategorisationRule
mapping its merchant/description to the new category, so future imports
from the same merchant are auto-categorised. Scoped to entry_source ==
"csv_import" -- the Gherkin's Given is explicitly "an imported
transaction ... was left Uncategorised", and manual entries can't
actually reach "Uncategorised" today anyway (FINTRACK-15's AC2 requires a
category on manual entry).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date as date_type

from apps.api.domain.repositories.categorisation_rule_repository import (
    CategorisationRuleRepository,
)
from apps.api.domain.models.transaction import Money, Transaction
from apps.api.domain.repositories.transaction_repository import (
    TransactionNotFoundError,
    TransactionRepository,
)

UNCATEGORISED = "Uncategorised"


@dataclass(frozen=True)
class UpdateTransactionCommand:
    transaction_id: uuid.UUID
    user_id: uuid.UUID
    amount: str | None = None
    category: str | None = None
    transaction_date: date_type | None = None
    note: str | None = None


class UpdateTransactionHandler:
    def __init__(
        self,
        transaction_repository: TransactionRepository,
        categorisation_rule_repository: CategorisationRuleRepository,
    ) -> None:
        self._transactions = transaction_repository
        self._categorisation_rules = categorisation_rule_repository

    async def handle(self, command: UpdateTransactionCommand) -> Transaction:
        transaction = await self._transactions.get_by_id_for_user(
            command.transaction_id, command.user_id
        )
        if transaction is None:
            # Same outcome whether the id never existed or belongs to
            # another user -- see TransactionRepository's docstring.
            raise TransactionNotFoundError("Transaction not found")

        previous_category = transaction.category
        entry_source = transaction.entry_source
        merchant_pattern = transaction.note

        amount = Money.parse(command.amount) if command.amount is not None else None
        transaction.apply_update(
            amount=amount,
            category=command.category,
            transaction_date=command.transaction_date,
            note=command.note,
        )

        await self._transactions.update(transaction)

        # FINTRACK-17 AC3: an imported transaction's category correction
        # (away from "Uncategorised") feeds back into the user's personal
        # rule set. Requires a merchant/description to pattern-match
        # against -- a note-less transaction has nothing to key a rule on.
        if (
            entry_source == "csv_import"
            and previous_category == UNCATEGORISED
            and transaction.category != UNCATEGORISED
            and merchant_pattern
        ):
            await self._categorisation_rules.upsert(
                user_id=command.user_id,
                merchant_pattern=merchant_pattern,
                category=transaction.category,
            )

        return transaction
