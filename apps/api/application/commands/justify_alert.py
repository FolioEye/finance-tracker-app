"""JustifyAlertCommand + handler. Story: FINTRACK-25 (AC1/AC2/AC5/AC7).

Justifying an alert is the ONLY way an AlertJustification row is ever
created or its ceiling raised -- there is no separate direct-write
endpoint for justifications, mirroring FINTRACK-22's own "alerts are only
ever created as a side effect" precedent (see alerts.py's module
docstring).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from apps.api.domain.models.alert import AlertType
from apps.api.domain.models.alert_justification import AlertJustification
from apps.api.domain.repositories.alert_justification_repository import (
    AlertJustificationRepository,
)
from apps.api.domain.repositories.alert_repository import AlertNotFoundError, AlertRepository
from apps.api.domain.repositories.transaction_repository import (
    TransactionNotFoundError,
    TransactionRepository,
)


class InvalidAlertTypeForJustificationError(Exception):
    """Raised when the target alert is not a LARGE_TRANSACTION alert.
    AC7: THRESHOLD_CROSSING alerts cannot be justified -- there's no
    per-transaction amount to build a ceiling from, and the concept
    doesn't map onto a recurring budget-percentage crossing."""


@dataclass(frozen=True)
class JustifyAlertCommand:
    alert_id: uuid.UUID
    user_id: uuid.UUID


class JustifyAlertHandler:
    def __init__(
        self,
        alert_repository: AlertRepository,
        alert_justification_repository: AlertJustificationRepository,
        transaction_repository: TransactionRepository,
    ) -> None:
        self._alerts = alert_repository
        self._justifications = alert_justification_repository
        self._transactions = transaction_repository

    async def handle(self, command: JustifyAlertCommand) -> None:
        alert = await self._alerts.get_by_id_for_user(command.alert_id, command.user_id)
        if alert is None:
            # Same one-error-for-both-cases IDOR shape as
            # DismissAlertHandler -- "doesn't exist" and "belongs to
            # someone else" are indistinguishable to the caller.
            raise AlertNotFoundError("Alert not found")

        if alert.alert_type != AlertType.LARGE_TRANSACTION:
            raise InvalidAlertTypeForJustificationError(
                "Justification only applies to large-transaction alerts"
            )

        # alert.transaction_id is always set for a LARGE_TRANSACTION alert
        # (see Alert.new_large_transaction), and the transaction it points
        # at was already validated -- and scoped to this same user_id --
        # at creation time, so a missing transaction here would indicate
        # data corruption, not a normal user-facing error path. Still
        # looked up scoped by user_id rather than trusted blindly, per
        # this codebase's IDOR discipline.
        transaction = await self._transactions.get_by_id_for_user(
            alert.transaction_id, command.user_id
        )
        if transaction is None:
            raise TransactionNotFoundError("Transaction not found")

        amount = transaction.amount.value
        existing = await self._justifications.get_for_user_and_category(
            command.user_id, alert.category
        )
        if existing is None:
            justification = AlertJustification.new(
                user_id=command.user_id, category=alert.category, ceiling_amount=amount
            )
            await self._justifications.add(justification)
        elif existing.raise_ceiling_if_higher(amount):
            await self._justifications.update(existing)
