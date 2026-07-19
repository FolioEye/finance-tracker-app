"""SQLAlchemy adapter implementing the AlertRepository port. Story: FINTRACK-22.

Every query filtered by user_id (except find_by_transaction_id, which is
scoped by the transaction_id's own uniqueness -- see its docstring) and
parameterised throughout, per this project's IDOR-prevention and SQLi
discipline.
"""
from __future__ import annotations

import uuid
from datetime import date as date_type
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.domain.models.alert import Alert, AlertType
from apps.api.domain.repositories.alert_repository import AlertRepository
from apps.api.infrastructure.database.models import AlertModel


def _to_domain(row: AlertModel) -> Alert:
    return Alert(
        id=row.id,
        user_id=row.user_id,
        category=row.category,
        alert_type=AlertType(row.alert_type),
        period_start=row.period_start,
        fired_at=row.fired_at,
        threshold_pct=row.threshold_pct,
        transaction_id=row.transaction_id,
        dismissed_at=row.dismissed_at,
    )


class SqlAlchemyAlertRepository(AlertRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, alert: Alert) -> None:
        row = AlertModel(
            id=alert.id,
            user_id=alert.user_id,
            category=alert.category,
            alert_type=alert.alert_type.value,
            period_start=alert.period_start,
            fired_at=alert.fired_at,
            threshold_pct=alert.threshold_pct,
            transaction_id=alert.transaction_id,
            dismissed_at=alert.dismissed_at,
        )
        self._session.add(row)
        await self._session.flush()

    async def get_by_id_for_user(self, alert_id: uuid.UUID, user_id: uuid.UUID) -> Optional[Alert]:
        stmt = select(AlertModel).where(
            and_(AlertModel.id == alert_id, AlertModel.user_id == user_id)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return _to_domain(row) if row else None

    async def find_active_threshold_crossing(
        self,
        user_id: uuid.UUID,
        category: str,
        period_start: date_type,
        threshold_pct: Decimal,
    ) -> Optional[Alert]:
        stmt = select(AlertModel).where(
            and_(
                AlertModel.user_id == user_id,
                AlertModel.category == category,
                AlertModel.alert_type == AlertType.THRESHOLD_CROSSING.value,
                AlertModel.period_start == period_start,
                AlertModel.threshold_pct == threshold_pct,
            )
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return _to_domain(row) if row else None

    async def find_by_transaction_id(self, transaction_id: uuid.UUID) -> Optional[Alert]:
        # Not filtered by user_id: a transaction_id is already globally
        # unique and only ever belongs to one user (enforced by
        # Transaction's own IDOR discipline at creation time), so there's
        # no cross-user leak risk in looking it up directly -- this is an
        # internal idempotency check, never exposed as a client-facing
        # lookup-by-transaction-id endpoint.
        stmt = select(AlertModel).where(AlertModel.transaction_id == transaction_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return _to_domain(row) if row else None

    async def list_for_user(self, user_id: uuid.UUID, include_dismissed: bool = False) -> list[Alert]:
        conditions = [AlertModel.user_id == user_id]
        if not include_dismissed:
            conditions.append(AlertModel.dismissed_at.is_(None))
        stmt = select(AlertModel).where(and_(*conditions)).order_by(AlertModel.fired_at.desc())
        result = await self._session.execute(stmt)
        return [_to_domain(row) for row in result.scalars().all()]

    async def update(self, alert: Alert) -> None:
        stmt = select(AlertModel).where(
            and_(AlertModel.id == alert.id, AlertModel.user_id == alert.user_id)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return  # caller already checked existence
        row.dismissed_at = alert.dismissed_at
        await self._session.flush()
