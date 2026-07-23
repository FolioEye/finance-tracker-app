"""ConfirmSubscriptionCommand + handler. Story: FINTRACK-18 (AC3).

Confirming is a positive acknowledgment -- it does not change future
detection behaviour (only DISMISSED/NOT_SUBSCRIPTION are treated as
terminal by detect_subscriptions_for_transaction.py), it just marks the
row as user-reviewed.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from apps.api.domain.repositories.subscription_repository import (
    SubscriptionNotFoundError,
    SubscriptionRepository,
)


@dataclass(frozen=True)
class ConfirmSubscriptionCommand:
    subscription_id: uuid.UUID
    user_id: uuid.UUID


class ConfirmSubscriptionHandler:
    def __init__(self, subscription_repository: SubscriptionRepository) -> None:
        self._subscriptions = subscription_repository

    async def handle(self, command: ConfirmSubscriptionCommand) -> None:
        subscription = await self._subscriptions.get_by_id_for_user(
            command.subscription_id, command.user_id
        )
        if subscription is None:
            # Same one-error-for-both-cases shape as AlertNotFoundError/
            # TransactionNotFoundError -- IDOR-prevention discipline.
            raise SubscriptionNotFoundError("Subscription not found")

        subscription.confirm()
        await self._subscriptions.update(subscription)
