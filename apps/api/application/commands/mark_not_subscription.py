"""MarkNotSubscriptionCommand + handler. Story: FINTRACK-18 (AC1/AC5).

A distinct action from dismiss: this is the user explicitly saying "this
was never a subscription" rather than "not now". Both are terminal for
detection purposes (see TERMINAL_STATUSES in domain.models.subscription),
but kept as separate status values rather than collapsed into one so the
audit trail/UI can distinguish "I don't want to see this" from "the
system was wrong about this."
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from apps.api.domain.repositories.subscription_repository import (
    SubscriptionNotFoundError,
    SubscriptionRepository,
)


@dataclass(frozen=True)
class MarkNotSubscriptionCommand:
    subscription_id: uuid.UUID
    user_id: uuid.UUID


class MarkNotSubscriptionHandler:
    def __init__(self, subscription_repository: SubscriptionRepository) -> None:
        self._subscriptions = subscription_repository

    async def handle(self, command: MarkNotSubscriptionCommand) -> None:
        subscription = await self._subscriptions.get_by_id_for_user(
            command.subscription_id, command.user_id
        )
        if subscription is None:
            raise SubscriptionNotFoundError("Subscription not found")

        subscription.mark_not_subscription()
        await self._subscriptions.update(subscription)
