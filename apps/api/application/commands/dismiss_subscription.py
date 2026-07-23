"""DismissSubscriptionCommand + handler. Story: FINTRACK-18 (AC1/AC5).

Dismissing marks this merchant as DISMISSED, which
detect_subscriptions_for_transaction.py treats as terminal -- AC5's "not
re-suggested" guarantee lives there, not in this handler.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from apps.api.domain.repositories.subscription_repository import (
    SubscriptionNotFoundError,
    SubscriptionRepository,
)


@dataclass(frozen=True)
class DismissSubscriptionCommand:
    subscription_id: uuid.UUID
    user_id: uuid.UUID


class DismissSubscriptionHandler:
    def __init__(self, subscription_repository: SubscriptionRepository) -> None:
        self._subscriptions = subscription_repository

    async def handle(self, command: DismissSubscriptionCommand) -> None:
        subscription = await self._subscriptions.get_by_id_for_user(
            command.subscription_id, command.user_id
        )
        if subscription is None:
            raise SubscriptionNotFoundError("Subscription not found")

        subscription.dismiss()
        await self._subscriptions.update(subscription)
