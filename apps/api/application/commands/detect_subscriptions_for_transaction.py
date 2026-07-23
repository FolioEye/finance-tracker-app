"""DetectSubscriptionsForTransactionCommand + handler. Story: FINTRACK-18.

Runs after a transaction is successfully created (called from the
transactions API endpoint, not from CreateTransactionHandler itself --
same composition-at-the-presentation-layer pattern as
EvaluateAlertsForTransactionHandler/ADR-014, so a bug here can never turn
a successful transaction write into a failed request).

AC6 ("re-runs when new transactions are added"): every call re-fetches
every one of this user's transactions matching the same merchant and
re-clusters from scratch, rather than incrementally updating a running
average. Simpler and correct by construction; the transaction volume per
merchant per user is small enough (recurring charges, by definition) that
re-scanning is cheap.

AC5 ("dismissed pattern not re-suggested"): enforced here, not in the
domain entity -- if an existing row's status is in TERMINAL_STATUSES,
this handler returns without touching it at all, regardless of what the
clustering function finds.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date as date_type
from decimal import Decimal
from typing import Optional

from apps.api.domain.models.subscription import (
    TERMINAL_STATUSES,
    Subscription,
    _Occurrence,
    detect_pattern,
    normalise_merchant,
)
from apps.api.domain.repositories.subscription_repository import SubscriptionRepository
from apps.api.domain.repositories.transaction_repository import TransactionRepository


@dataclass(frozen=True)
class DetectSubscriptionsForTransactionCommand:
    user_id: uuid.UUID
    transaction_id: uuid.UUID
    note: Optional[str]
    amount: Decimal
    transaction_date: date_type


class DetectSubscriptionsForTransactionHandler:
    def __init__(
        self,
        subscription_repository: SubscriptionRepository,
        transaction_repository: TransactionRepository,
    ) -> None:
        self._subscriptions = subscription_repository
        self._transactions = transaction_repository

    async def handle(
        self, command: DetectSubscriptionsForTransactionCommand
    ) -> Optional[Subscription]:
        if not command.note:
            # A note-less transaction has nothing to group by -- same
            # "no merchant text, nothing to key on" limitation
            # UpdateTransactionHandler's categorisation feedback loop
            # already accepts for FINTRACK-17.
            return None

        merchant = normalise_merchant(command.note)

        existing = await self._subscriptions.find_by_user_and_merchant(
            command.user_id, merchant
        )
        if existing is not None and existing.status in TERMINAL_STATUSES:
            return None

        matching_transactions = await self._transactions.list_all_for_user_by_merchant(
            user_id=command.user_id, merchant=merchant
        )
        occurrences = [
            _Occurrence(
                amount=t.amount.value,
                transaction_date=t.transaction_date,
                transaction_id=t.id,
            )
            for t in matching_transactions
        ]

        pattern = detect_pattern(occurrences)
        if pattern is None:
            # Not (yet) a recognisable pattern -- leave any existing
            # non-terminal row exactly as it was rather than clearing it,
            # since a single subsequent irregular transaction shouldn't
            # erase an otherwise-solid detected pattern.
            return None

        amount_estimate, interval_days = pattern

        if existing is None:
            subscription = Subscription.new_detected(
                user_id=command.user_id,
                merchant=merchant,
                amount_estimate=amount_estimate,
                interval_days=interval_days,
                occurrences=len(occurrences),
                last_transaction_id=command.transaction_id,
            )
            await self._subscriptions.add(subscription)
            return subscription

        existing.refresh_stats(
            amount_estimate=amount_estimate,
            interval_days=interval_days,
            occurrences=len(occurrences),
            last_transaction_id=command.transaction_id,
        )
        await self._subscriptions.update(existing)
        return existing
