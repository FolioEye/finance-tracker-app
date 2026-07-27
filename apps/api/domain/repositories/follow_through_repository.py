"""Port (interface) for FollowThroughRecord persistence. Story: FINTRACK-23."""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import date as date_type
from typing import Optional

from apps.api.domain.models.follow_through_record import FollowThroughRecord


class FollowThroughRecordNotFoundError(Exception):
    """Raised when a record doesn't exist, or doesn't belong to the
    requesting user -- same deliberate one-error-for-both-cases shape as
    AlertNotFoundError/BudgetNotFoundError, mapped to 404 (not 403) at the
    API layer so a response can't be used to confirm another user's
    record id exists (IDOR-prevention discipline)."""


class FollowThroughRepository(ABC):
    @abstractmethod
    async def add(self, record: FollowThroughRecord) -> None:
        ...

    @abstractmethod
    async def get_by_id_for_user(
        self, record_id: uuid.UUID, user_id: uuid.UUID
    ) -> Optional[FollowThroughRecord]:
        ...

    @abstractmethod
    async def get_for_user_and_period(
        self, user_id: uuid.UUID, period_start: date_type
    ) -> Optional[FollowThroughRecord]:
        """Idempotency check used by EnsureFollowThroughRecordHandler --
        at most one record per user per calendar day."""
        ...

    @abstractmethod
    async def list_for_user(self, user_id: uuid.UUID) -> list[FollowThroughRecord]:
        """All records for the user, most recent period_start first.
        Callers needing only a rolling window filter in the application
        layer, same division of responsibility as list_alerts.py."""
        ...

    @abstractmethod
    async def update(self, record: FollowThroughRecord) -> None:
        ...
