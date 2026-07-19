"""DismissAlertCommand + handler. Story: FINTRACK-22 (AC4/AC5).

Dismissing an alert marks it seen; it must never suppress or delete the
underlying threshold-crossing/large-transaction record, and must never
prevent a future, distinct crossing from firing its own alert (AC4) --
enforced by EvaluateAlertsForTransactionHandler's dedup key already
including period_start, not by anything in this handler.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from apps.api.domain.repositories.alert_repository import AlertNotFoundError, AlertRepository


@dataclass(frozen=True)
class DismissAlertCommand:
    alert_id: uuid.UUID
    user_id: uuid.UUID


class DismissAlertHandler:
    def __init__(self, alert_repository: AlertRepository) -> None:
        self._alerts = alert_repository

    async def handle(self, command: DismissAlertCommand) -> None:
        alert = await self._alerts.get_by_id_for_user(command.alert_id, command.user_id)
        if alert is None:
            # Same one-error-for-both-cases shape as TransactionNotFoundError
            # and BudgetNotFoundError: "doesn't exist" and "belongs to
            # someone else" map to the identical 404, so a caller can't use
            # this endpoint to confirm another user's alert id exists
            # (IDOR-prevention discipline; covers the BA's "attempt to
            # dismiss another user's alert" security scenario).
            raise AlertNotFoundError("Alert not found")

        if alert.dismissed_at is None:
            alert.dismiss()
            await self._alerts.update(alert)
