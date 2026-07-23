"""Port (interface) for subscription persistence. Infrastructure provides
the adapter. Story: FINTRACK-18.
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Optional

from apps.api.domain.models.subscription import Subscription


class SubscriptionNotFoundError(Exception):
    """Raised when a subscription doesn't exist, or doesn't belong to the
    requesting user -- same deliberate one-error-for-both-cases shape as
    AlertNotFoundError/TransactionNotFoundError, mapped to 404 (not 403)
    at the API layer so a response can't be used to confirm another
    user's subscription id exists."""


class SubscriptionRepository(ABC):
    @abstractmethod
    async def add(self, subscription: Subscription) -> None:
        ...

    @abstractmethod
    async def get_by_id_for_user(
        self, subscription_id: uuid.UUID, user_id: uuid.UUID
    ) -> Optional[Subscription]:
        ...

    @abstractmethod
    async def find_by_user_and_merchant(
        self, user_id: uuid.UUID, merchant: str
    ) -> Optional[Subscription]:
        """Idempotency/upsert check -- AC1 keys one row per (user_id,
        merchant), so re-detection updates this row rather than inserting
        a duplicate. Also how AC5's "dismissed pattern not re-suggested"
        is enforced: the caller checks this row's status before deciding
        whether to refresh stats or leave it alone."""
        ...

    @abstractmethod
    async def list_for_user(self, user_id: uuid.UUID, include_dismissed: bool = False) -> list[Subscription]:
        """Active-only by default -- excludes DISMISSED and
        NOT_SUBSCRIPTION rows unless include_dismissed=True, same
        AlertRepository.list_for_user convention."""
        ...

    @abstractmethod
    async def update(self, subscription: Subscription) -> None:
        ...
