"""ListSubscriptionsQuery + handler. Story: FINTRACK-18 (AC2).

Surfaces subscriptions for the current user (the "dedicated Subscriptions
view"), active-only by default -- excludes DISMISSED/NOT_SUBSCRIPTION.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from apps.api.domain.models.subscription import Subscription
from apps.api.domain.repositories.subscription_repository import SubscriptionRepository


@dataclass(frozen=True)
class ListSubscriptionsQuery:
    user_id: uuid.UUID
    include_dismissed: bool = False


class ListSubscriptionsHandler:
    def __init__(self, subscription_repository: SubscriptionRepository) -> None:
        self._subscriptions = subscription_repository

    async def handle(self, query: ListSubscriptionsQuery) -> list[Subscription]:
        return await self._subscriptions.list_for_user(
            user_id=query.user_id, include_dismissed=query.include_dismissed
        )
