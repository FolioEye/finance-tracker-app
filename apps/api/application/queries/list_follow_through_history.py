"""ListFollowThroughHistoryQuery + handler. Story: FINTRACK-23.

Scoped entirely to the authenticated user_id (never a client-supplied
identifier) -- same IDOR-prevention discipline as list_alerts.py. Runs
the shared read-time reconciliation (AC4) before returning, so a caller
never sees a stale PENDING row that should already read as IGNORED.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date as date_type
from typing import Callable

from apps.api.application.queries.follow_through_reconciliation import (
    reconcile_overdue_records,
)
from apps.api.domain.models.follow_through_record import FollowThroughRecord
from apps.api.domain.repositories.follow_through_repository import FollowThroughRepository


@dataclass(frozen=True)
class ListFollowThroughHistoryQuery:
    user_id: uuid.UUID


class ListFollowThroughHistoryHandler:
    def __init__(
        self,
        follow_through_repository: FollowThroughRepository,
        clock: Callable[[], date_type] = date_type.today,
    ) -> None:
        self._records = follow_through_repository
        self._clock = clock

    async def handle(self, query: ListFollowThroughHistoryQuery) -> list[FollowThroughRecord]:
        records = await self._records.list_for_user(query.user_id)
        return await reconcile_overdue_records(self._records, records, self._clock)
