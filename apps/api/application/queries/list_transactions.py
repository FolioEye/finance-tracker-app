"""ListTransactionsQuery + handler -- covers AC4 ("Appears immediately in
list"). Cursor-based pagination (not offset), per constraint matrix.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from apps.api.domain.repositories.transaction_repository import (
    TransactionPage,
    TransactionRepository,
)

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


@dataclass(frozen=True)
class ListTransactionsQuery:
    user_id: uuid.UUID
    limit: int = DEFAULT_PAGE_SIZE
    cursor: str | None = None


class ListTransactionsHandler:
    def __init__(self, transaction_repository: TransactionRepository) -> None:
        self._transactions = transaction_repository

    async def handle(self, query: ListTransactionsQuery) -> TransactionPage:
        limit = max(1, min(query.limit, MAX_PAGE_SIZE))
        return await self._transactions.list_for_user(
            user_id=query.user_id, limit=limit, cursor=query.cursor
        )
