"""Unit tests for CreateCategorisationRuleHandler (FINTRACK-17, AC1 + the
Gherkin's injection-attempt security scenario). Pure application-layer
tests -- a fake in-memory repository stands in for the real SQLAlchemy
adapter, same pattern as tests/unit/test_transaction_handlers.py and
tests/unit/test_import_command_handlers.py's FakeCategorisationRuleRepository.
"""
from __future__ import annotations

import uuid

import pytest

from apps.api.application.commands.create_categorisation_rule import (
    CreateCategorisationRuleCommand,
    CreateCategorisationRuleHandler,
)
from apps.api.domain.models.categorisation_rule import CategorisationRule, SuspiciousInputError


class FakeCategorisationRuleRepository:
    """In-memory stand-in for SqlAlchemyCategorisationRuleRepository.
    Mirrors the real adapter's upsert semantics (one rule per normalised
    merchant_pattern per user) in plain Python -- no real DB in this file.
    """

    def __init__(self) -> None:
        self.rules: dict[uuid.UUID, CategorisationRule] = {}

    async def add(self, rule: CategorisationRule) -> None:
        self.rules[rule.id] = rule

    async def list_for_user(self, user_id: uuid.UUID) -> list[CategorisationRule]:
        return [r for r in self.rules.values() if r.user_id == user_id]

    async def find_by_pattern_for_user(self, user_id: uuid.UUID, merchant_pattern: str):
        normalised = merchant_pattern.strip().upper()
        for rule in self.rules.values():
            if rule.user_id == user_id and rule.merchant_pattern == normalised:
                return rule
        return None

    async def upsert(self, user_id: uuid.UUID, merchant_pattern: str, category: str) -> CategorisationRule:
        existing = await self.find_by_pattern_for_user(user_id, merchant_pattern)
        if existing is not None:
            existing.apply_correction(category)
            return existing
        rule = CategorisationRule.new(user_id=user_id, merchant_pattern=merchant_pattern, category=category)
        await self.add(rule)
        return rule


@pytest.fixture
def categorisation_rules() -> FakeCategorisationRuleRepository:
    return FakeCategorisationRuleRepository()


@pytest.fixture
def handler(categorisation_rules: FakeCategorisationRuleRepository) -> CreateCategorisationRuleHandler:
    return CreateCategorisationRuleHandler(categorisation_rule_repository=categorisation_rules)


# ---------------------------------------------------------------------------
# Happy path (AC1 / Gherkin scenario 4's implicit "save the rule" step)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_categorisation_rule_creates_a_new_rule(
    handler: CreateCategorisationRuleHandler, categorisation_rules: FakeCategorisationRuleRepository
) -> None:
    user_id = uuid.uuid4()
    rule = await handler.handle(
        CreateCategorisationRuleCommand(user_id=user_id, merchant_pattern="Starbucks", category="Coffee & Dining")
    )
    assert rule.merchant_pattern == "STARBUCKS"
    assert rule.category == "Coffee & Dining"
    assert rule.user_id == user_id
    assert len(await categorisation_rules.list_for_user(user_id)) == 1


@pytest.mark.asyncio
async def test_create_categorisation_rule_upserts_rather_than_duplicates_for_the_same_pattern(
    handler: CreateCategorisationRuleHandler, categorisation_rules: FakeCategorisationRuleRepository
) -> None:
    user_id = uuid.uuid4()
    await handler.handle(
        CreateCategorisationRuleCommand(user_id=user_id, merchant_pattern="Starbucks", category="Coffee & Dining")
    )
    updated = await handler.handle(
        CreateCategorisationRuleCommand(user_id=user_id, merchant_pattern="starbucks", category="Business Expenses")
    )
    rules = await categorisation_rules.list_for_user(user_id)
    assert len(rules) == 1
    assert updated.category == "Business Expenses"


@pytest.mark.asyncio
async def test_create_categorisation_rule_scopes_rules_per_user(
    handler: CreateCategorisationRuleHandler, categorisation_rules: FakeCategorisationRuleRepository
) -> None:
    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    await handler.handle(
        CreateCategorisationRuleCommand(user_id=user_a, merchant_pattern="Starbucks", category="Coffee & Dining")
    )
    await handler.handle(
        CreateCategorisationRuleCommand(user_id=user_b, merchant_pattern="Starbucks", category="Business Expenses")
    )
    assert len(await categorisation_rules.list_for_user(user_a)) == 1
    assert len(await categorisation_rules.list_for_user(user_b)) == 1
    assert (await categorisation_rules.list_for_user(user_a))[0].category == "Coffee & Dining"
    assert (await categorisation_rules.list_for_user(user_b))[0].category == "Business Expenses"


# ---------------------------------------------------------------------------
# Security -- matches the BA's Gherkin scenario 4 exactly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_categorisation_rule_rejects_sqli_shaped_merchant_pattern(
    handler: CreateCategorisationRuleHandler, categorisation_rules: FakeCategorisationRuleRepository
) -> None:
    user_id = uuid.uuid4()
    with pytest.raises(SuspiciousInputError, match="Invalid characters detected"):
        await handler.handle(
            CreateCategorisationRuleCommand(
                user_id=user_id, merchant_pattern="'; DROP TABLE rules; --", category="Groceries"
            )
        )
    assert await categorisation_rules.list_for_user(user_id) == []


@pytest.mark.asyncio
async def test_create_categorisation_rule_rejects_sqli_shaped_category(
    handler: CreateCategorisationRuleHandler, categorisation_rules: FakeCategorisationRuleRepository
) -> None:
    user_id = uuid.uuid4()
    with pytest.raises(SuspiciousInputError, match="Invalid characters detected"):
        await handler.handle(
            CreateCategorisationRuleCommand(
                user_id=user_id, merchant_pattern="Starbucks", category="'; DROP TABLE rules; --"
            )
        )
    assert await categorisation_rules.list_for_user(user_id) == []


@pytest.mark.asyncio
async def test_create_categorisation_rule_rejects_empty_merchant_pattern(
    handler: CreateCategorisationRuleHandler,
) -> None:
    with pytest.raises(SuspiciousInputError, match="Merchant pattern is required"):
        await handler.handle(
            CreateCategorisationRuleCommand(user_id=uuid.uuid4(), merchant_pattern="   ", category="Groceries")
        )
