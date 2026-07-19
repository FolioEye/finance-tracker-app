"""CreateBudgetCommand + handler -- covers AC1 (set monthly budget per
category). Story: FINTRACK-20.

Rejects (BudgetAlreadyExistsError, mapped to 409 at the API layer) if the
user already has a budget for this category -- the Gherkin models
"create" and "edit" as distinct operations (AC4's separate edit
scenario), so a second POST for the same category should not silently
overwrite; the caller should PATCH instead. This is a deliberate
departure from FINTRACK-17's CategorisationRule.upsert() pattern, where a
second submission for the same merchant *is* the desired UX (re-correcting
the same merchant again) -- budgets have no equivalent "resubmission is
itself the correction" story, so plain create-or-409 is the simpler and
more predictable contract.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from apps.api.domain.models.budget import Budget
from apps.api.domain.repositories.budget_repository import (
    BudgetAlreadyExistsError,
    BudgetRepository,
)


@dataclass(frozen=True)
class CreateBudgetCommand:
    user_id: uuid.UUID
    category: str
    monthly_limit: str


class CreateBudgetHandler:
    def __init__(self, budget_repository: BudgetRepository) -> None:
        self._budgets = budget_repository

    async def handle(self, command: CreateBudgetCommand) -> Budget:
        # Raises InvalidBudgetAmountError / SuspiciousInputError -- mapped
        # to 400 at the API layer -- before we even check for a
        # pre-existing budget, so a malformed request never reaches the
        # uniqueness check.
        budget = Budget.new(
            user_id=command.user_id,
            category=command.category,
            monthly_limit_raw=command.monthly_limit,
        )

        existing = await self._budgets.get_by_category_for_user(command.user_id, budget.category)
        if existing is not None:
            raise BudgetAlreadyExistsError(
                f"A budget for '{budget.category}' already exists -- use PATCH to edit it"
            )

        await self._budgets.add(budget)
        return budget
