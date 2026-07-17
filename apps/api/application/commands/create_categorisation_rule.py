"""CreateCategorisationRuleCommand + handler -- lets a user directly add a
personal merchant -> category rule. Story: FINTRACK-17 (AC1, and the
Gherkin's injection-attempt security scenario).

Uses CategorisationRuleRepository.upsert() rather than a bare add(): a
second rule submitted for the same merchant pattern updates the existing
one instead of creating a silent duplicate the matching engine would
otherwise have to disambiguate between.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from apps.api.domain.models.categorisation_rule import CategorisationRule
from apps.api.domain.repositories.categorisation_rule_repository import (
    CategorisationRuleRepository,
)


@dataclass(frozen=True)
class CreateCategorisationRuleCommand:
    user_id: uuid.UUID
    merchant_pattern: str
    category: str


class CreateCategorisationRuleHandler:
    def __init__(self, categorisation_rule_repository: CategorisationRuleRepository) -> None:
        self._rules = categorisation_rule_repository

    async def handle(self, command: CreateCategorisationRuleCommand) -> CategorisationRule:
        # Raises SuspiciousInputError -- mapped to 400 at the API layer
        # (the Gherkin's injection-attempt scenario).
        return await self._rules.upsert(
            user_id=command.user_id,
            merchant_pattern=command.merchant_pattern,
            category=command.category,
        )
