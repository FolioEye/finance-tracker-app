"""DeleteBudgetCommand + handler -- covers AC4's remove half
("... removable anytime"). Story: FINTRACK-20.

Removing a budget only removes the limit -- it does not touch any
Transaction rows, so past spend in that category remains fully visible in
transaction history (the Gherkin's remove scenario is explicit about
this). There is nothing else to cascade: a Budget has no child records.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from apps.api.domain.repositories.budget_repository import (
    BudgetNotFoundError,
    BudgetRepository,
)


@dataclass(frozen=True)
class DeleteBudgetCommand:
    budget_id: uuid.UUID
    user_id: uuid.UUID


class DeleteBudgetHandler:
    def __init__(self, budget_repository: BudgetRepository) -> None:
        self._budgets = budget_repository

    async def handle(self, command: DeleteBudgetCommand) -> None:
        deleted = await self._budgets.delete(command.budget_id, command.user_id)
        if not deleted:
            raise BudgetNotFoundError("Budget not found")
