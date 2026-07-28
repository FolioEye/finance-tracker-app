"""EnsureFollowThroughRecordCommand + handler. Story: FINTRACK-23, extended
by FINTRACK-27.

Idempotent get-or-create: called from the presentation layer immediately
after GetWeeklyRecommendationHandler produces a recommendation (see
recommendations.py), never from inside FINTRACK-21's own handler --
that handler is untouched by this story, per the architecture decision in
follow_through_record.py's module docstring.

Safe under repeated calls the same day (e.g. the user refreshes the page
twice): get_for_user_and_period is checked first, so a second call in the
same period returns the existing record rather than creating a duplicate
or clobbering an already-actioned one.

recommendation_key (FINTRACK-27): the fine-grained identity (category or
merchant) the presentation layer derives from the Recommendation DTO --
see recommendations.py's _recommendation_key helper. None for NEUTRAL.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date as date_type
from typing import Optional

from apps.api.domain.models.follow_through_record import FollowThroughRecord
from apps.api.domain.repositories.follow_through_repository import FollowThroughRepository


@dataclass(frozen=True)
class EnsureFollowThroughRecordCommand:
    user_id: uuid.UUID
    period_start: date_type
    recommendation_type: str
    recommendation_key: Optional[str] = None


class EnsureFollowThroughRecordHandler:
    def __init__(self, follow_through_repository: FollowThroughRepository) -> None:
        self._records = follow_through_repository

    async def handle(self, command: EnsureFollowThroughRecordCommand) -> FollowThroughRecord:
        existing = await self._records.get_for_user_and_period(
            command.user_id, command.period_start
        )
        if existing is not None:
            return existing

        record = FollowThroughRecord.new_pending(
            user_id=command.user_id,
            period_start=command.period_start,
            recommendation_type=command.recommendation_type,
            recommendation_key=command.recommendation_key,
        )
        await self._records.add(record)
        return record
