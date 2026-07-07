"""UpdateTransactionCommand + handler -- covers AC5 ("Editable/deletable").

Not covered by any of the BA's 4 Gherkin scenarios for FINTRACK-15 (all
four are create-only) -- implemented anyway since AC5 explicitly requires
it. Flagged to QA Lead: this handler has no Gherkin-mapped test yet.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date as date_type

from apps.api.domain.models.transaction import Money, Transaction
from apps.api.domain.repositories.transaction_repository import (
    TransactionNotFoundError,
    TransactionRepository,
)


@dataclass(frozen=True)
class UpdateTransactionCommand:
    transaction_id: uuid.UUID
    user_id: uuid.UUID
    amount: str | None = None
    category: str | None = None
    transaction_date: date_type | None = None
    note: str | None = None


class UpdateTransactionHandler:
    def __init__(self, transaction_repository: TransactionRepository) -> None:
        self._transactions = transaction_repository

    async def handle(self, command: UpdateTransactionCommand) -> Transaction:
        transaction = await self._transactions.get_by_id_for_user(
            command.transaction_id, command.user_id
        )
        if transaction is None:
            # Same outcome whether the id never existed or belongs to
            # another user -- see TransactionRepository's docstring.
            raise TransactionNotFoundError("Transaction not found")

        amount = Money.parse(command.amount) if command.amount is not None else None
        transaction.apply_update(
            amount=amount,
            category=command.category,
            transaction_date=command.transaction_date,
            note=command.note,
        )

        await self._transactions.update(transaction)
        return transaction
