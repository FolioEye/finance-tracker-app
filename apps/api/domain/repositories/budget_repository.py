"""Port (interface) for budget persistence. Infrastructure provides the
adapter. Story: FINTRACK-20.
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Optional

from apps.api.domain.models.budget import Budget


class BudgetNotFoundError(Exception):
    """Raised when a budget doesn't exist, or doesn't belong to the
    requesting user -- same deliberate one-error-for-both-cases shape as
    TransactionNotFoundError (maps to 404, not 403, so a caller can't use
    the response to confirm another user's budget id exists)."""


class BudgetAlreadyExistsError(Exception):
    """Raised when creating a budget for a category the user already has
    one for -- the Gherkin models create and edit as distinct operations
    (AC4), so a second POST for the same category is a 409, guiding the
    caller to PATCH instead of silently overwriting."""


class BudgetRepository(ABC):
    @abstractmethod
    async def add(self, budget: Budget) -> None:
        ...

    @abstractmethod
    async def get_by_id_for_user(
        self, budget_id: uuid.UUID, user_id: uuid.UUID
    ) -> Optional[Budget]:
        """Returns None if the budget doesn't exist OR belongs to a
        different user -- callers should raise BudgetNotFoundError in the
        latter case rather than distinguishing them, per this project's
        IDOR-prevention discipline."""
        ...

    @abstractmethod
    async def get_by_category_for_user(
        self, user_id: uuid.UUID, category: str
    ) -> Optional[Budget]:
        ...

    @abstractmethod
    async def list_for_user(self, user_id: uuid.UUID) -> list[Budget]:
        ...

    @abstractmethod
    async def update(self, budget: Budget) -> None:
        ...

    @abstractmethod
    async def delete(self, budget_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Returns True if a row belonging to user_id was deleted, False if
        no matching row existed (already-gone or not this user's)."""
        ...
