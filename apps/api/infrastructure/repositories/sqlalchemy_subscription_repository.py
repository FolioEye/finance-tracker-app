"""SQLAlchemy adapter implementing the SubscriptionRepository port.
Story: FINTRACK-18.

Every query filtered by user_id and parameterised throughout, per this
project's IDOR-prevention and SQLi discipline.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.domain.models.subscription import Subscription, SubscriptionStatus
from apps.api.domain.repositories.subscription_repository import SubscriptionRepository
from apps.api.infrastructure.database.models import SubscriptionModel


def _to_domain(row: SubscriptionModel) -> Subscription:
    return Subscription(
        id=row.id,
        user_id=row.user_id,
        merchant=row.merchant,
        amount_estimate=row.amount_estimate,
        interval_days=row.interval_days,
        occurrences=row.occurrences,
        status=SubscriptionStatus(row.status),
        last_transaction_id=row.last_transaction_id,
        first_detected_at=row.first_detected_at,
        last_seen_at=row.last_seen_at,
        updated_at=row.updated_at,
    )


class SqlAlchemySubscriptionRepository(SubscriptionRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, subscription: Subscription) -> None:
        row = SubscriptionModel(
            id=subscription.id,
            user_id=subscription.user_id,
            merchant=subscription.merchant,
            amount_estimate=subscription.amount_estimate,
            interval_days=subscription.interval_days,
            occurrences=subscription.occurrences,
            status=subscription.status.value,
            last_transaction_id=subscription.last_transaction_id,
            first_detected_at=subscription.first_detected_at,
            last_seen_at=subscription.last_seen_at,
            updated_at=subscription.updated_at,
        )
        self._session.add(row)
        await self._session.flush()

    async def get_by_id_for_user(
        self, subscription_id: uuid.UUID, user_id: uuid.UUID
    ) -> Optional[Subscription]:
        stmt = select(SubscriptionModel).where(
            and_(SubscriptionModel.id == subscription_id, SubscriptionModel.user_id == user_id)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return _to_domain(row) if row else None

    async def find_by_user_and_merchant(
        self, user_id: uuid.UUID, merchant: str
    ) -> Optional[Subscription]:
        stmt = select(SubscriptionModel).where(
            and_(SubscriptionModel.user_id == user_id, SubscriptionModel.merchant == merchant)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return _to_domain(row) if row else None

    async def list_for_user(
        self, user_id: uuid.UUID, include_dismissed: bool = False
    ) -> list[Subscription]:
        conditions = [SubscriptionModel.user_id == user_id]
        if not include_dismissed:
            conditions.append(
                SubscriptionModel.status.notin_(
                    [SubscriptionStatus.DISMISSED.value, SubscriptionStatus.NOT_SUBSCRIPTION.value]
                )
            )
        stmt = (
            select(SubscriptionModel)
            .where(and_(*conditions))
            .order_by(SubscriptionModel.last_seen_at.desc())
        )
        result = await self._session.execute(stmt)
        return [_to_domain(row) for row in result.scalars().all()]

    async def update(self, subscription: Subscription) -> None:
        stmt = select(SubscriptionModel).where(
            and_(
                SubscriptionModel.id == subscription.id,
                SubscriptionModel.user_id == subscription.user_id,
            )
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return  # caller already checked existence
        row.amount_estimate = subscription.amount_estimate
        row.interval_days = subscription.interval_days
        row.occurrences = subscription.occurrences
        row.status = subscription.status.value
        row.last_transaction_id = subscription.last_transaction_id
        row.last_seen_at = subscription.last_seen_at
        row.updated_at = subscription.updated_at
        await self._session.flush()
