"""SQLAlchemy adapter implementing the CategorisationRuleRepository port.
Story: FINTRACK-17.

Every query is parameterised via SQLAlchemy's query builder and filtered
by user_id -- same IDOR-prevention/no-string-concatenated-SQL discipline
as sqlalchemy_transaction_repository.py.
"""
from __future__ import annotations

import uuid

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.domain.models.categorisation_rule import CategorisationRule
from apps.api.domain.repositories.categorisation_rule_repository import (
    CategorisationRuleRepository,
)
from apps.api.infrastructure.database.models import CategorisationRuleModel


def _to_domain(row: CategorisationRuleModel) -> CategorisationRule:
    return CategorisationRule(
        id=row.id,
        user_id=row.user_id,
        merchant_pattern=row.merchant_pattern,
        category=row.category,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlAlchemyCategorisationRuleRepository(CategorisationRuleRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, rule: CategorisationRule) -> None:
        row = CategorisationRuleModel(
            id=rule.id,
            user_id=rule.user_id,
            merchant_pattern=rule.merchant_pattern,
            category=rule.category,
            created_at=rule.created_at,
            updated_at=rule.updated_at,
        )
        self._session.add(row)
        await self._session.flush()

    async def list_for_user(self, user_id: uuid.UUID) -> list[CategorisationRule]:
        stmt = select(CategorisationRuleModel).where(CategorisationRuleModel.user_id == user_id)
        result = await self._session.execute(stmt)
        return [_to_domain(r) for r in result.scalars().all()]

    async def find_by_pattern_for_user(
        self, user_id: uuid.UUID, merchant_pattern: str
    ) -> CategorisationRule | None:
        normalised = merchant_pattern.strip().upper()
        stmt = select(CategorisationRuleModel).where(
            and_(
                CategorisationRuleModel.user_id == user_id,
                CategorisationRuleModel.merchant_pattern == normalised,
            )
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return _to_domain(row) if row else None

    async def upsert(
        self, user_id: uuid.UUID, merchant_pattern: str, category: str
    ) -> CategorisationRule:
        existing = await self.find_by_pattern_for_user(user_id, merchant_pattern)
        if existing is not None:
            existing.apply_correction(category)  # raises SuspiciousInputError if invalid
            stmt = select(CategorisationRuleModel).where(CategorisationRuleModel.id == existing.id)
            result = await self._session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is not None:
                row.category = existing.category
                row.updated_at = existing.updated_at
                await self._session.flush()
            return existing

        rule = CategorisationRule.new(
            user_id=user_id, merchant_pattern=merchant_pattern, category=category
        )
        await self.add(rule)
        return rule
