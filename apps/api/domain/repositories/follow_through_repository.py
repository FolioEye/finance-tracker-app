"""Port (interface) for FollowThroughRecord persistence. Story: FINTRACK-23,
extended by FINTRACK-27."""
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
    async def list_recent_for_user_type_and_key(
        self,
        user_id: uuid.UUID,
        recommendation_type: str,
        recommendation_key: str,
        limit: int = 10,
    ) -> list[FollowThroughRecord]:
        """FINTRACK-27. Most recent `limit` records (most recent
        period_start first) matching this exact (recommendation_type,
        recommendation_key) pair for this user -- backs
        RecommendationPrioritisationService's rolling-window read. A
        dedicated, narrowly-scoped query rather than filtering
        list_for_user client-side, same division of responsibility as
        get_for_user_and_period."""
        ...

    @abstractmethod
    async def update(self, record: FollowThroughRecord) -> None:
        ...
