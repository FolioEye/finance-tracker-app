"""DeleteTransactionCommand + handler -- covers AC5 ("Editable/deletable").

Same gap as update_transaction.py: not covered by any of the BA's 4
Gherkin scenarios, implemented anyway since AC5 requires it.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from apps.api.domain.repositories.transaction_repository import (
    TransactionNotFoundError,
    TransactionRepository,
)


@dataclass(frozen=True)
class DeleteTransactionCommand:
    transaction_id: uuid.UUID
    user_id: uuid.UUID


class DeleteTransactionHandler:
    def __init__(self, transaction_repository: TransactionRepository) -> None:
        self._transactions = transaction_repository

    async def handle(self, command: DeleteTransactionCommand) -> None:
        deleted = await self._transactions.delete(command.transaction_id, command.user_id)
        if not deleted:
            raise TransactionNotFoundError("Transaction not found")
