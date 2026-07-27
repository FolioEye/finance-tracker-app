"""SQLAlchemy adapter implementing the AlertJustificationRepository port.
Story: FINTRACK-25.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.domain.models.alert_justification import AlertJustification
from apps.api.domain.repositories.alert_justification_repository import (
    AlertJustificationRepository,
)
from apps.api.infrastructure.database.models import AlertJustificationModel


def _to_domain(row: AlertJustificationModel) -> AlertJustification:
    return AlertJustification(
        id=row.id,
        user_id=row.user_id,
        category=row.category,
        ceiling_amount=row.ceiling_amount,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlAlchemyAlertJustificationRepository(AlertJustificationRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_user_and_category(
        self, user_id: uuid.UUID, category: str
    ) -> Optional[AlertJustification]:
        stmt = select(AlertJustificationModel).where(
            and_(
                AlertJustificationModel.user_id == user_id,
                AlertJustificationModel.category == category,
            )
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return _to_domain(row) if row else None

    async def add(self, justification: AlertJustification) -> None:
        row = AlertJustificationModel(
            id=justification.id,
            user_id=justification.user_id,
            category=justification.category,
            ceiling_amount=justification.ceiling_amount,
            created_at=justification.created_at,
            updated_at=justification.updated_at,
        )
        self._session.add(row)
        await self._session.flush()

    async def update(self, justification: AlertJustification) -> None:
        stmt = select(AlertJustificationModel).where(
            AlertJustificationModel.id == justification.id
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return  # caller already checked existence
        row.ceiling_amount = justification.ceiling_amount
        row.updated_at = justification.updated_at
        await self._session.flush()
