"""FollowThroughRecord domain entity. Story: FINTRACK-23 (Action
Follow-Through Tracking).

Architecture decision (resolves the open question BA flagged): FINTRACK-21's
GetWeeklyRecommendationHandler stays exactly as-is -- untouched, still
compute-on-read, still regenerating "this week's" recommendation fresh from
a rolling 7-day window on every call (see that handler's own docstring). It
has no stable notion of "the same recommendation" across requests, so this
story doesn't try to give it one.

Instead, a FollowThroughRecord is a *separate*, write-time-persisted entity
keyed by (user_id, period_start) where period_start is simply the calendar
date on which the user was first shown a recommendation that day -- the
presentation layer creates one (idempotently, get-or-create) the first
time a given user hits GET /recommendations/weekly on a given day, via
EnsureFollowThroughRecordHandler. This is the same shape of problem
FINTRACK-22's Alert entity solved (write-time persistence purely to give an
otherwise-ephemeral event a stable, actionable identity), applied here
without requiring any change to FINTRACK-21's own handler or its dependency
wiring -- satisfying the BA's second phrasing of the open question directly.

recommendation_type is captured at creation time for display/audit purposes
only; it is not part of the record's identity (period_start is what one
user can have at most one row for).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

# AC4: "unactioned past 7 days auto-marked ignored" -- a scenario reads
# "received a recommendation 8 days ago and took no action" expects it
# ignored, i.e. the cutoff is *more than* 7 days, not "on or after day 7".
FOLLOW_THROUGH_WINDOW_DAYS = 7


class FollowThroughStatus(str, Enum):
    PENDING = "PENDING"
    DONE = "DONE"
    DISMISSED = "DISMISSED"
    IGNORED = "IGNORED"


@dataclass
class FollowThroughRecord:
    id: uuid.UUID
    user_id: uuid.UUID
    period_start: date_type
    recommendation_type: str
    status: FollowThroughStatus
    created_at: datetime
    actioned_at: Optional[datetime] = None

    @staticmethod
    def new_pending(
        user_id: uuid.UUID,
        period_start: date_type,
        recommendation_type: str,
    ) -> "FollowThroughRecord":
        return FollowThroughRecord(
            id=uuid.uuid4(),
            user_id=user_id,
            period_start=period_start,
            recommendation_type=recommendation_type,
            status=FollowThroughStatus.PENDING,
            created_at=datetime.now(timezone.utc),
        )

    def mark_done(self) -> None:
        self.status = FollowThroughStatus.DONE
        self.actioned_at = datetime.now(timezone.utc)

    def mark_dismissed(self) -> None:
        self.status = FollowThroughStatus.DISMISSED
        self.actioned_at = datetime.now(timezone.utc)

    def mark_ignored(self) -> None:
        """System-driven transition (AC4), not a user action -- deliberately
        does not set actioned_at, which is reserved for a real user click
        (mark_done/mark_dismissed) so a later "who actually did something"
        query can still tell the two apart if ever needed."""
        self.status = FollowThroughStatus.IGNORED

    def is_overdue(self, today: date_type, window_days: int = FOLLOW_THROUGH_WINDOW_DAYS) -> bool:
        """True when this is still PENDING and more than `window_days` have
        elapsed since period_start -- the read-time reconciliation check
        AC4 relies on (see ReconcileOverdueFollowThroughRecordsHandler)."""
        if self.status != FollowThroughStatus.PENDING:
            return False
        return (today - self.period_start).days > window_days
