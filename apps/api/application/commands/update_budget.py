"""UpdateBudgetCommand + handler -- covers AC4's edit half ("editable ...
anytime"). Story: FINTRACK-20.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from apps.api.domain.models.budget import Budget
from apps.api.domain.repositories.budget_repository import (
    BudgetNotFoundError,
    BudgetRepository,
)


@dataclass(frozen=True)
class UpdateBudgetCommand:
    budget_id: uuid.UUID
    user_id: uuid.UUID
    monthly_limit: str


class UpdateBudgetHandler:
    def __init__(self, budget_repository: BudgetRepository) -> None:
        self._budgets = budget_repository

    async def handle(self, command: UpdateBudgetCommand) -> Budget:
        budget = await self._budgets.get_by_id_for_user(command.budget_id, command.user_id)
        if budget is None:
            # Same outcome whether the id never existed or belongs to
            # another user -- see BudgetRepository's docstring.
            raise BudgetNotFoundError("Budget not found")

        # Raises InvalidBudgetAmountError -- mapped to 400 at the API layer.
        budget.apply_update(monthly_limit_raw=command.monthly_limit)
        await self._budgets.update(budget)
        return budget
