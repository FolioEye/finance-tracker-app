"""CreateTransactionCommand + handler -- the use case for FINTRACK-15
(Add Manual Transaction).

Written to the shape the PM's architecture constraint expects to be
shared with future CSV import (FINTRACK-16) and receipt OCR (P1): a
single command carrying the same fields regardless of entry_source. Only
manual entry constructs and executes it directly today; a future bulk
importer would construct many of these, stage them for user review, and
execute each on confirm rather than calling this handler once per row
unreviewed.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date as date_type

from apps.api.domain.models.transaction import Money, Transaction
from apps.api.domain.repositories.transaction_repository import TransactionRepository


@dataclass(frozen=True)
class CreateTransactionCommand:
    user_id: uuid.UUID
    amount: str
    category: str
    transaction_date: date_type
    note: str | None = None
    entry_source: str = "manual"  # forward-looking: "csv_import", "receipt_ocr" later


class CreateTransactionHandler:
    def __init__(self, transaction_repository: TransactionRepository) -> None:
        self._transactions = transaction_repository

    async def handle(self, command: CreateTransactionCommand) -> Transaction:
        # Raises InvalidAmountError / AmountExceedsMaximumError -- mapped
        # to 400 at the API layer.
        amount = Money.parse(command.amount)

        # Raises InvalidAmountError (empty category) or SuspiciousInputError
        # (SQLi-shaped category/note) -- both mapped to 400.
        transaction = Transaction.new(
            user_id=command.user_id,
            amount=amount,
            category=command.category,
            transaction_date=command.transaction_date,
            note=command.note,
            entry_source=command.entry_source,
        )

        await self._transactions.add(transaction)
        return transaction
