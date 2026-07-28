"""Follow-through-based recommendation prioritisation. Story: FINTRACK-27.

Resolves BA's AC2 concrete rule (Jira, 2026-07-28 BA pass): rolling window
= last 10 times this exact (recommendation_type, recommendation_key)
combination was shown to the user; minimum sample = 3 *resolved*
occurrences before a combination can be deprioritised; threshold = below
30% follow-through in that window; recovery = instant the moment the most
recent resolved occurrence was DONE (not a rate recompute alone -- BA's
explicit rule, "not a fixed timer, not permanent suppression").

Deliberately keyed by (recommendation_type, recommendation_key) rather
than recommendation_type alone: FollowThroughRecord only stored the
coarse type before this story (BUDGET_RISK/NEW_SUBSCRIPTION/
SPENDING_SPIKE), which can't distinguish "dining-out" spikes from
"entertainment" spikes the way the BA's own Gherkin examples do --
recommendation_key is this story's addition (migration 0010) carrying
the category (BUDGET_RISK, SPENDING_SPIKE) or merchant (NEW_SUBSCRIPTION)
that the coarse type alone can't express.

"Occurrences" for both the minimum-sample and rate calculations count
only *resolved* records (DONE/DISMISSED/IGNORED) -- a still-PENDING
record (not yet 7 days old, no action taken) hasn't produced an outcome
to judge yet, so counting it either way would misstate the rate, same
reasoning GetFollowThroughRateHandler already applies to its own
denominator. This is a Tech Lead interpretation of BA's "occurrences"
wording (BA's text doesn't distinguish shown-vs-resolved explicitly) --
flagged here rather than silently assumed, for QA Lead to confirm against
the signed Gherkin when writing tests.

GetWeeklyRecommendationHandler calls this per within-tier candidate (not
batched) -- acceptable at expected FinTrack data volumes (a handful of
at-risk budgets/spiking categories per user per call); a batched
repository method would be the first optimisation if this ever shows up
in profiling.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date as date_type
from decimal import Decimal
from typing import Callable, Optional

from apps.api.application.queries.follow_through_reconciliation import (
    reconcile_overdue_records,
)
from apps.api.domain.models.follow_through_record import FollowThroughStatus
from apps.api.domain.repositories.follow_through_repository import FollowThroughRepository

# BA's concrete AC2 rule (Jira, 2026-07-28 BA pass) -- documented constants,
# same convention as FINTRACK-21's BASELINE_WEEKS/SPIKE_MULTIPLIER.
ROLLING_WINDOW = 10
MIN_SAMPLE = 3
DEPRIORITISATION_THRESHOLD_PCT = Decimal("30")


@dataclass(frozen=True)
class DeprioritisationResult:
    deprioritised: bool
    reason_detail: Optional[str] = None  # e.g. "acted on only 2 of last 10 times"


class RecommendationPrioritisationService:
    def __init__(
        self,
        follow_through_repository: FollowThroughRepository,
        clock: Callable[[], date_type] = date_type.today,
    ) -> None:
        self._records = follow_through_repository
        self._clock = clock

    async def evaluate(
        self,
        user_id: uuid.UUID,
        recommendation_type: str,
        recommendation_key: Optional[str],
    ) -> DeprioritisationResult:
        if recommendation_key is None:
            # NEUTRAL and anything without a fine-grained identity is never
            # deprioritised -- there's nothing to track it against.
            return DeprioritisationResult(deprioritised=False)

        recent = await self._records.list_recent_for_user_type_and_key(
            user_id, recommendation_type, recommendation_key, limit=ROLLING_WINDOW
        )
        recent = await reconcile_overdue_records(self._records, recent, self._clock)

        resolved = [r for r in recent if r.status != FollowThroughStatus.PENDING]
        if len(resolved) < MIN_SAMPLE:
            # Edge case: too few occurrences (BA scenario) -- also covers a
            # brand-new type with zero history (empty `resolved`).
            return DeprioritisationResult(deprioritised=False)

        # Recovery rule (BA, AC2): the most recent resolved occurrence being
        # DONE instantly restores normal priority regardless of the rolling
        # rate -- simple and explainable per AC3, not a fixed timer.
        if resolved[0].status == FollowThroughStatus.DONE:
            return DeprioritisationResult(deprioritised=False)

        done = sum(1 for r in resolved if r.status == FollowThroughStatus.DONE)
        total = len(resolved)
        rate_pct = (Decimal(done) / Decimal(total)) * Decimal(100)
        if rate_pct < DEPRIORITISATION_THRESHOLD_PCT:
            return DeprioritisationResult(
                deprioritised=True,
                reason_detail=f"acted on only {done} of last {total} times",
            )
        return DeprioritisationResult(deprioritised=False)
