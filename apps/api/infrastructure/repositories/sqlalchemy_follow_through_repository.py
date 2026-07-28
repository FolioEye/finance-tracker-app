"""SQLAlchemy adapter implementing the FollowThroughRepository port. Story:
FINTRACK-23, extended by FINTRACK-27.

Every query filtered by user_id, parameterised throughout -- same
IDOR-prevention and SQLi discipline as sqlalchemy_alert_repository.py.
"""
from __future__ import annotations

import uuid
from datetime import date as date_type
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.domain.models.follow_through_record import FollowThroughRecord, FollowThroughStatus
from apps.api.domain.repositories.follow_through_repository import FollowThroughRepository
from apps.api.infrastructure.database.models import FollowThroughRecordModel


def _to_domain(row: FollowThroughRecordModel) -> FollowThroughRecord:
    return FollowThroughRecord(
        id=row.id,
        user_id=row.user_id,
        period_start=row.period_start,
        recommendation_type=row.recommendation_type,
        recommendation_key=row.recommendation_key,
        status=FollowThroughStatus(row.status),
        created_at=row.created_at,
        actioned_at=row.actioned_at,
    )


class SqlAlchemyFollowThroughRepository(FollowThroughRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, record: FollowThroughRecord) -> None:
        row = FollowThroughRecordModel(
            id=record.id,
            user_id=record.user_id,
            period_start=record.period_start,
            recommendation_type=record.recommendation_type,
            recommendation_key=record.recommendation_key,
            status=record.status.value,
            created_at=record.created_at,
            actioned_at=record.actioned_at,
        )
        self._session.add(row)
        await self._session.flush()

    async def get_by_id_for_user(
        self, record_id: uuid.UUID, user_id: uuid.UUID
    ) -> Optional[FollowThroughRecord]:
        stmt = select(FollowThroughRecordModel).where(
            and_(FollowThroughRecordModel.id == record_id, FollowThroughRecordModel.user_id == user_id)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return _to_domain(row) if row else None

    async def get_for_user_and_period(
        self, user_id: uuid.UUID, period_start: date_type
    ) -> Optional[FollowThroughRecord]:
        stmt = select(FollowThroughRecordModel).where(
            and_(
                FollowThroughRecordModel.user_id == user_id,
                FollowThroughRecordModel.period_start == period_start,
            )
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return _to_domain(row) if row else None

    async def list_for_user(self, user_id: uuid.UUID) -> list[FollowThroughRecord]:
        stmt = (
            select(FollowThroughRecordModel)
            .where(FollowThroughRecordModel.user_id == user_id)
            .order_by(FollowThroughRecordModel.period_start.desc())
        )
        result = await self._session.execute(stmt)
        return [_to_domain(row) for row in result.scalars().all()]

    async def list_recent_for_user_type_and_key(
        self,
        user_id: uuid.UUID,
        recommendation_type: str,
        recommendation_key: str,
        limit: int = 10,
    ) -> list[FollowThroughRecord]:
        stmt = (
            select(FollowThroughRecordModel)
            .where(
                and_(
                    FollowThroughRecordModel.user_id == user_id,
                    FollowThroughRecordModel.recommendation_type == recommendation_type,
                    FollowThroughRecordModel.recommendation_key == recommendation_key,
                )
            )
            .order_by(FollowThroughRecordModel.period_start.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [_to_domain(row) for row in result.scalars().all()]

    async def update(self, record: FollowThroughRecord) -> None:
        stmt = select(FollowThroughRecordModel).where(
            and_(
                FollowThroughRecordModel.id == record.id,
                FollowThroughRecordModel.user_id == record.user_id,
            )
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return  # caller already checked existence
        row.status = record.status.value
        row.actioned_at = record.actioned_at
        await self._session.flush()
