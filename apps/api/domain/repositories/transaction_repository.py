"""Port (interface) for transaction persistence. Infrastructure provides the adapter."""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from apps.api.domain.models.transaction import Transaction


class TransactionNotFoundError(Exception):
    """Raised when a transaction doesn't exist, or doesn't belong to the
    requesting user -- deliberately the same error/outcome for both cases
    (see transactions.py: this maps to 404, not 403, so a caller can't use
    the response to confirm another user's transaction ID exists)."""


@dataclass(frozen=True)
class TransactionPage:
    """One page of cursor-paginated results."""

    items: list[Transaction]
    next_cursor: str | None  # opaque; None means this is the last page


class TransactionRepository(ABC):
    @abstractmethod
    async def add(self, transaction: Transaction) -> None:
        ...

    @abstractmethod
    async def get_by_id_for_user(
        self, transaction_id: uuid.UUID, user_id: uuid.UUID
    ) -> Optional[Transaction]:
        """Returns None if the transaction doesn't exist OR belongs to a
        different user -- callers should raise TransactionNotFoundError in
        the latter case rather than distinguishing them, per constraint
        matrix's IDOR-prevention approach."""
        ...

    @abstractmethod
    async def list_for_user(
        self, user_id: uuid.UUID, limit: int, cursor: str | None
    ) -> TransactionPage:
        """Most-recent-first, cursor-based (not offset) pagination."""
        ...

    @abstractmethod
    async def update(self, transaction: Transaction) -> None:
        ...

    @abstractmethod
    async def delete(self, transaction_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Returns True if a row belonging to user_id was deleted, False if
        no matching row existed (already-gone or not this user's)."""
        ...
