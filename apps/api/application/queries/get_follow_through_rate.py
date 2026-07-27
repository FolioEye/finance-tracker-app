"""GetFollowThroughRateQuery + handler. Story: FINTRACK-23 (AC3).

Follow-Through Rate = done / (done + dismissed + ignored) over a rolling
window -- PENDING records (no action taken yet, and not yet past the
7-day auto-ignore window) are excluded from both numerator and
denominator entirely: they're not yet a resolved outcome one way or the
other, so counting them either as a success or a failure would misstate
the rate. Runs the same read-time reconciliation as
ListFollowThroughHistoryHandler first, so an overdue PENDING record is
correctly counted as IGNORED rather than excluded.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date as date_type
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable, Optional

from apps.api.application.queries.follow_through_reconciliation import (
    reconcile_overdue_records,
)
from apps.api.domain.models.follow_through_record import FollowThroughStatus
from apps.api.domain.repositories.follow_through_repository import FollowThroughRepository

# How far back "the rolling window" looks for rate purposes -- not
# specified numerically by the ACs, so made an explicit, documented
# constant (same convention as FINTRACK-21's BASELINE_WEEKS/
# SPIKE_MULTIPLIER) rather than an unstated assumption. 8 weeks: long
# enough to be statistically meaningful at roughly one recommendation
# surfaced per day, short enough to still reflect recent behaviour.
RATE_ROLLING_WINDOW_DAYS = 56


@dataclass(frozen=True)
class GetFollowThroughRateQuery:
    user_id: uuid.UUID


@dataclass(frozen=True)
class FollowThroughRateResult:
    done_count: int
    dismissed_count: int
    ignored_count: int
    rate_pct: Optional[Decimal]  # None when the denominator is 0 (no resolved actions yet)


class GetFollowThroughRateHandler:
    def __init__(
        self,
        follow_through_repository: FollowThroughRepository,
        clock: Callable[[], date_type] = date_type.today,
    ) -> None:
        self._records = follow_through_repository
        self._clock = clock

    async def handle(self, query: GetFollowThroughRateQuery) -> FollowThroughRateResult:
        today = self._clock()
        all_records = await self._records.list_for_user(query.user_id)
        reconciled = await reconcile_overdue_records(self._records, all_records, self._clock)

        window_start = today - timedelta(days=RATE_ROLLING_WINDOW_DAYS - 1)
        in_window = [r for r in reconciled if r.period_start >= window_start]

        done = sum(1 for r in in_window if r.status == FollowThroughStatus.DONE)
        dismissed = sum(1 for r in in_window if r.status == FollowThroughStatus.DISMISSED)
        ignored = sum(1 for r in in_window if r.status == FollowThroughStatus.IGNORED)

        denominator = done + dismissed + ignored
        rate_pct: Optional[Decimal]
        if denominator == 0:
            rate_pct = None
        else:
            rate_pct = (Decimal(done) / Decimal(denominator) * Decimal(100)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

        return FollowThroughRateResult(
            done_count=done,
            dismissed_count=dismissed,
            ignored_count=ignored,
            rate_pct=rate_pct,
        )
