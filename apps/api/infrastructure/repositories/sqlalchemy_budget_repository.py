"""SQLAlchemy adapter implementing the BudgetRepository port.
Story: FINTRACK-20.

Every query is parameterised via SQLAlchemy's query builder and filtered
by user_id -- same IDOR-prevention/no-string-concatenated-SQL discipline
as sqlalchemy_transaction_repository.py and
sqlalchemy_categorisation_rule_repository.py.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.domain.models.budget import Budget
from apps.api.domain.repositories.budget_repository import BudgetRepository
from apps.api.infrastructure.database.models import BudgetModel


def _to_domain(row: BudgetModel) -> Budget:
    return Budget(
        id=row.id,
        user_id=row.user_id,
        category=row.category,
        monthly_limit=row.monthly_limit,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlAlchemyBudgetRepository(BudgetRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, budget: Budget) -> None:
        row = BudgetModel(
            id=budget.id,
            user_id=budget.user_id,
            category=budget.category,
            monthly_limit=budget.monthly_limit,
            created_at=budget.created_at,
            updated_at=budget.updated_at,
        )
        self._session.add(row)
        await self._session.flush()

    async def get_by_id_for_user(
        self, budget_id: uuid.UUID, user_id: uuid.UUID
    ) -> Optional[Budget]:
        stmt = select(BudgetModel).where(
            and_(BudgetModel.id == budget_id, BudgetModel.user_id == user_id)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return _to_domain(row) if row else None

    async def get_by_category_for_user(
        self, user_id: uuid.UUID, category: str
    ) -> Optional[Budget]:
        stmt = select(BudgetModel).where(
            and_(BudgetModel.user_id == user_id, BudgetModel.category == category)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return _to_domain(row) if row else None

    async def list_for_user(self, user_id: uuid.UUID) -> list[Budget]:
        stmt = select(BudgetModel).where(BudgetModel.user_id == user_id)
        result = await self._session.execute(stmt)
        return [_to_domain(r) for r in result.scalars().all()]

    async def update(self, budget: Budget) -> None:
        stmt = select(BudgetModel).where(
            and_(BudgetModel.id == budget.id, BudgetModel.user_id == budget.user_id)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return  # caller (the command handler) already checked existence
        row.monthly_limit = budget.monthly_limit
        row.updated_at = budget.updated_at
        await self._session.flush()

    async def delete(self, budget_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        stmt = delete(BudgetModel).where(
            and_(BudgetModel.id == budget_id, BudgetModel.user_id == user_id)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount > 0
