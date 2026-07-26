"""GetWeeklyRecommendationQuery + handler. Story: FINTRACK-21.

Compute-on-read, same shape as GetBudgetOverviewHandler (FINTRACK-20) and
GetSpendingInsightsHandler (FINTRACK-19) -- no new persisted domain
entity. Unlike Alert (FINTRACK-22), a recommendation doesn't need a
"already told them" write-time record: it's regenerated fresh each time
the endpoint is called, and AC1's "one per week" is satisfied by there
being exactly one recommendation *per request*, not by deduplicating
against a stored history. If a future story needs "don't repeat the same
recommendation twice in a row" that would be the trigger to add
persistence -- out of scope here (BA's Gherkin doesn't test for it).

Three trigger types, checked in a fixed priority order (architecture
decision -- BA flagged this as an open question, not prescribed):

1. BUDGET_RISK -- highest priority. Money is actively at risk of being
   overspent *this period*; every other trigger is informational by
   comparison.
2. NEW_SUBSCRIPTION -- a recurring charge the user hasn't acted on yet.
   Time-sensitive in a softer sense (subscriptions compound monthly the
   longer they go unnoticed) but nothing is currently over-limit.
3. SPENDING_SPIKE -- lowest priority. The softest signal of the three: a
   single unusually-heavy week can easily be a legitimate one-off
   purchase, not a behaviour problem.

AC3's "no meaningful pattern -> neutral message" falls out of this
naturally rather than being a special-cased "is this a new user" check:
a user with no budgets, no subscriptions, and no unusual spend simply
fails all three trigger checks and reaches the neutral fallback. This
also covers a genuinely brand-new user with zero transactions without
any dedicated branch for that case.

"This week" is a *rolling* trailing-7-day window ending at generation
time (today, inclusive, back 6 days), not a calendar Mon-Sun week --
deliberate, since this is generated on-demand rather than by a scheduled
weekly batch job; a rolling window means "this week" always means "the
last 7 days," regardless of which day the user happens to check.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date as date_type
from datetime import timedelta
from decimal import Decimal
from enum import Enum
from typing import Callable, Optional

from apps.api.application.queries.date_ranges import current_month_bounds
from apps.api.domain.models.subscription import SubscriptionStatus
from apps.api.domain.repositories.budget_repository import BudgetRepository
from apps.api.domain.repositories.subscription_repository import SubscriptionRepository
from apps.api.domain.repositories.transaction_repository import TransactionRepository

# AC2/Gherkin scenario 1's own example (80% of budget). A documented
# constant, not a magic number -- same convention as
# subscription.py's MIN_OCCURRENCES/AMOUNT_TOLERANCE_PCT.
BUDGET_RISK_THRESHOLD_PCT = Decimal("80")

ROLLING_WINDOW_DAYS = 7

# Spending-spike baseline: how many *prior* rolling weeks to average for
# a "recent average" to compare this week against. 4 prior weeks (28
# days) -- long enough to smooth out a single unusual prior week, short
# enough to still reflect recent behaviour rather than the user's entire
# history.
BASELINE_WEEKS = 4

# This week's spend in a category must be at least this many times the
# category's baseline weekly average to count as a "spike" -- avoids
# flagging routine week-to-week variance as a false signal.
SPIKE_MULTIPLIER = Decimal("1.5")


class RecommendationType(str, Enum):
    BUDGET_RISK = "BUDGET_RISK"
    NEW_SUBSCRIPTION = "NEW_SUBSCRIPTION"
    SPENDING_SPIKE = "SPENDING_SPIKE"
    NEUTRAL = "NEUTRAL"


@dataclass(frozen=True)
class GetWeeklyRecommendationQuery:
    user_id: uuid.UUID


@dataclass(frozen=True)
class Recommendation:
    type: RecommendationType
    message: str
    category: Optional[str] = None
    merchant: Optional[str] = None


# AC3: encouraging, never fabricating a claim about the user's spending
# (no numbers, no category names -- there's nothing to reference truthfully
# when no trigger has fired).
_NEUTRAL_MESSAGE = (
    "Nothing urgent needs your attention this week -- you're on track. Keep logging "
    "your spending and we'll flag anything worth a look as soon as it comes up."
)


def _rolling_window(today: date_type, days: int) -> tuple[date_type, date_type]:
    """[start, end) -- trailing `days`-day window ending at `today`
    inclusive, i.e. start = today - (days - 1)."""
    end = today + timedelta(days=1)
    start = today - timedelta(days=days - 1)
    return start, end


class GetWeeklyRecommendationHandler:
    def __init__(
        self,
        budget_repository: BudgetRepository,
        subscription_repository: SubscriptionRepository,
        transaction_repository: TransactionRepository,
        clock: Callable[[], date_type] = date_type.today,
    ) -> None:
        self._budgets = budget_repository
        self._subscriptions = subscription_repository
        self._transactions = transaction_repository
        # Same DI-for-determinism rationale as GetBudgetOverviewHandler --
        # QA Lead needs to pin "today" to exercise week-boundary and
        # month-boundary behaviour without depending on wall-clock time.
        self._clock = clock

    async def handle(self, query: GetWeeklyRecommendationQuery) -> Recommendation:
        today = self._clock()

        budget_risk = await self._check_budget_risk(query.user_id, today)
        if budget_risk is not None:
            return budget_risk

        new_subscription = await self._check_new_subscription(query.user_id, today)
        if new_subscription is not None:
            return new_subscription

        spending_spike = await self._check_spending_spike(query.user_id, today)
        if spending_spike is not None:
            return spending_spike

        return Recommendation(type=RecommendationType.NEUTRAL, message=_NEUTRAL_MESSAGE)

    async def _check_budget_risk(
        self, user_id: uuid.UUID, today: date_type
    ) -> Optional[Recommendation]:
        month_start, month_end = current_month_bounds(today)
        budgets = await self._budgets.list_for_user(user_id)
        if not budgets:
            return None

        spend_by_category = await self._transactions.sum_by_category_for_user_in_range(
            user_id, month_start, month_end
        )

        # Highest percent-used first -- if more than one budget is at
        # risk, the recommendation names the most urgent one.
        at_risk = sorted(
            (
                (budget, spend_by_category.get(budget.category, Decimal("0")))
                for budget in budgets
            ),
            key=lambda pair: (pair[1] / pair[0].monthly_limit) if pair[0].monthly_limit else Decimal("0"),
            reverse=True,
        )
        for budget, spent in at_risk:
            if not budget.monthly_limit:
                continue
            percent_used = (spent / budget.monthly_limit) * Decimal("100")
            if percent_used >= BUDGET_RISK_THRESHOLD_PCT:
                return Recommendation(
                    type=RecommendationType.BUDGET_RISK,
                    message=(
                        f"You've used {percent_used:.0f}% of your \"{budget.category}\" budget "
                        f"this month -- consider slowing down spending in this category for "
                        f"the rest of the month."
                    ),
                    category=budget.category,
                )
        return None

    async def _check_new_subscription(
        self, user_id: uuid.UUID, today: date_type
    ) -> Optional[Recommendation]:
        window_start, window_end = _rolling_window(today, ROLLING_WINDOW_DAYS)
        subscriptions = await self._subscriptions.list_for_user(user_id, include_dismissed=False)

        # Only DETECTED (not yet confirmed/dismissed) subscriptions newly
        # seen within the rolling window count -- a CONFIRMED subscription
        # is no longer "new," it's already-acknowledged.
        candidates = [
            sub
            for sub in subscriptions
            if sub.status == SubscriptionStatus.DETECTED
            and window_start <= sub.first_detected_at.date() < window_end
        ]
        if not candidates:
            return None

        # Most-recently-detected first if more than one is new this week.
        newest = max(candidates, key=lambda sub: sub.first_detected_at)
        return Recommendation(
            type=RecommendationType.NEW_SUBSCRIPTION,
            message=(
                f"We noticed a new recurring charge from \"{newest.merchant}\" "
                f"(~${newest.amount_estimate:.2f} every ~{newest.interval_days} days). "
                f"Worth a quick review to confirm it's one you still want."
            ),
            merchant=newest.merchant,
        )

    async def _check_spending_spike(
        self, user_id: uuid.UUID, today: date_type
    ) -> Optional[Recommendation]:
        this_week_start, this_week_end = _rolling_window(today, ROLLING_WINDOW_DAYS)
        this_week_spend = await self._transactions.sum_by_category_for_user_in_range(
            user_id, this_week_start, this_week_end
        )
        if not this_week_spend:
            return None

        baseline_days = ROLLING_WINDOW_DAYS * BASELINE_WEEKS
        baseline_start = this_week_start - timedelta(days=baseline_days)
        baseline_spend = await self._transactions.sum_by_category_for_user_in_range(
            user_id, baseline_start, this_week_start
        )

        best: Optional[tuple[str, Decimal, Decimal]] = None  # (category, this_week, baseline_avg)
        for category, spent_this_week in this_week_spend.items():
            baseline_total = baseline_spend.get(category)
            # No baseline history for this category -- can't call it a
            # "spike" against a comparison that doesn't exist yet; that
            # would be fabricating a claim, exactly what AC3 forbids.
            if not baseline_total:
                continue
            baseline_avg = baseline_total / Decimal(BASELINE_WEEKS)
            if baseline_avg <= 0:
                continue
            if spent_this_week >= baseline_avg * SPIKE_MULTIPLIER:
                if best is None or spent_this_week > best[1]:
                    best = (category, spent_this_week, baseline_avg)

        if best is None:
            return None

        category, spent_this_week, baseline_avg = best
        return Recommendation(
            type=RecommendationType.SPENDING_SPIKE,
            message=(
                f"Your \"{category}\" spending this week (${spent_this_week:.2f}) is well "
                f"above your recent average (${baseline_avg:.2f}/week) -- worth a quick look "
                f"to see if that's expected."
            ),
            category=category,
        )
