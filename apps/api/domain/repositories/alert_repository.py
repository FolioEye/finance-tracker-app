"""Port (interface) for alert persistence. Infrastructure provides the
adapter. Story: FINTRACK-22.
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import date as date_type
from decimal import Decimal
from typing import Optional

from apps.api.domain.models.alert import Alert


class AlertNotFoundError(Exception):
    """Raised when an alert doesn't exist, or doesn't belong to the
    requesting user -- same deliberate one-error-for-both-cases shape as
    BudgetNotFoundError/TransactionNotFoundError, mapped to 404 (not 403)
    at the API layer so a response can't be used to confirm another
    user's alert id exists."""


class AlertRepository(ABC):
    @abstractmethod
    async def add(self, alert: Alert) -> None:
        ...

    @abstractmethod
    async def get_by_id_for_user(self, alert_id: uuid.UUID, user_id: uuid.UUID) -> Optional[Alert]:
        ...

    @abstractmethod
    async def find_active_threshold_crossing(
        self,
        user_id: uuid.UUID,
        category: str,
        period_start: date_type,
        threshold_pct: Decimal,
    ) -> Optional[Alert]:
        """Idempotency check for AC5 -- called before inserting a new
        THRESHOLD_CROSSING alert so the same crossing never fires twice
        in the same period, regardless of how many transactions land in
        that category afterward."""
        ...

    @abstractmethod
    async def find_by_transaction_id(self, transaction_id: uuid.UUID) -> Optional[Alert]:
        """Idempotency check before inserting a new LARGE_TRANSACTION
        alert -- each triggering transaction gets at most one alert, even
        if alert evaluation were ever retried for the same transaction."""
        ...

    @abstractmethod
    async def list_for_user(self, user_id: uuid.UUID, include_dismissed: bool = False) -> list[Alert]:
        ...

    @abstractmethod
    async def update(self, alert: Alert) -> None:
        ...
