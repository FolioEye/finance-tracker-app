"""Port (interface) for categorisation-rule persistence. Infrastructure
provides the adapter. Story: FINTRACK-17.
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod

from apps.api.domain.models.categorisation_rule import CategorisationRule


class CategorisationRuleRepository(ABC):
    @abstractmethod
    async def add(self, rule: CategorisationRule) -> None:
        ...

    @abstractmethod
    async def list_for_user(self, user_id: uuid.UUID) -> list[CategorisationRule]:
        """All of a user's rules, for the auto-categorisation matching
        pass over a staged import (AC1)."""
        ...

    @abstractmethod
    async def find_by_pattern_for_user(
        self, user_id: uuid.UUID, merchant_pattern: str
    ) -> CategorisationRule | None:
        ...

    @abstractmethod
    async def upsert(
        self, user_id: uuid.UUID, merchant_pattern: str, category: str
    ) -> CategorisationRule:
        """Creates a new rule, or updates the category of an existing one
        matching the same normalised merchant_pattern for this user.

        Used both by the direct rule-creation endpoint and by the
        correction-feedback loop (update_transaction.py) -- both are the
        same underlying operation ("this user maps this merchant to this
        category from now on"), so they share one method rather than the
        codebase carrying two near-identical create-or-update paths.
        """
        ...
