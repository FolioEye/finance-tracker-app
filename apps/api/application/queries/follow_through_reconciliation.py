"""Shared read-time reconciliation helper for FollowThroughRecord. Story:
FINTRACK-23 (AC4).

There is no scheduled job runner in this stack (12-factor: stateless
processes, no new long-running worker introduced just for this), so AC4's
"unactioned past 7 days auto-marked ignored" is enforced lazily, the same
moment any read path touches a user's records -- same "read repair" shape
already used implicitly by FINTRACK-21's own compute-on-read design.
Both GetFollowThroughRateHandler and ListFollowThroughHistoryHandler call
this before doing their own read so neither can ever report a stale
PENDING record past its window.
"""
from __future__ import annotations

from datetime import date as date_type
from typing import Callable

from apps.api.domain.models.follow_through_record import FollowThroughRecord
from apps.api.domain.repositories.follow_through_repository import FollowThroughRepository


async def reconcile_overdue_records(
    repository: FollowThroughRepository,
    records: list[FollowThroughRecord],
    clock: Callable[[], date_type],
) -> list[FollowThroughRecord]:
    today = clock()
    for record in records:
        if record.is_overdue(today):
            record.mark_ignored()
            await repository.update(record)
    return records
