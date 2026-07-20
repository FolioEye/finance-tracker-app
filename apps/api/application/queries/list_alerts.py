"""ListAlertsQuery + handler. Story: FINTRACK-22.

Surfaces alerts for the current user, active-only by default.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from apps.api.domain.models.alert import Alert
from apps.api.domain.repositories.alert_repository import AlertRepository


@dataclass(frozen=True)
class ListAlertsQuery:
    user_id: uuid.UUID
    include_dismissed: bool = False


class ListAlertsHandler:
    def __init__(self, alert_repository: AlertRepository) -> None:
        self._alerts = alert_repository

    async def handle(self, query: ListAlertsQuery) -> list[Alert]:
        return await self._alerts.list_for_user(
            user_id=query.user_id, include_dismissed=query.include_dismissed
        )
