"""Unit tests for GetWeeklyRecommendationHandler (FINTRACK-21). Fakes
stand in for BudgetRepository, SubscriptionRepository, and
TransactionRepository -- same pattern as
tests/unit/test_spending_insights_handler.py's FakeTransactionRepository,
extended here with fake Budget/Subscription repos since this handler is
the first to depend on all three ports at once.

Every scenario below maps 1:1 to a scenario in
tests/features/FINTRACK-21-weekly-recommendation-engine.feature. No
Gherkin step text drove an implementation shortcut -- these assert
against the handler's actual documented priority order (BUDGET_RISK >
NEW_SUBSCRIPTION > SPENDING_SPIKE, see get_weekly_recommendation.py's
module docstring), which was Tech Lead's own architecture decision
resolving BA's open question, not something BA specified.

FakeFollowThroughRepository (FINTRACK-27): GetWeeklyRecommendationHandler
now requires a follow_through_repository to evaluate within-tier
follow-through-based reordering. Every scenario below predates that
story and seeds no follow-through history, so list_recent_for_user_type_
and_key always returns [] -- RecommendationPrioritisationService then
never deprioritises anything (see its own min-sample-size guard), so
these tests keep exercising exactly the base priority-chain behavior
they always did. FINTRACK-27's own reordering behavior is covered by
test_recommendation_prioritisation.py and the new within-tier reorder
tests, not here.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from apps.api.application.queries.get_weekly_recommendation import (
    BUDGET_RISK_THRESHOLD_PCT,
    GetWeeklyRecommendationHandler,
    GetWeeklyRecommendationQuery,
    RecommendationType,
)
from apps.api.domain.models.subscription import SubscriptionStatus


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class _FakeBudget:
    category: str
    monthly_limit: Decimal


class FakeBudgetRepository:
    def __init__(self) -> None:
        self._budgets: dict[uuid.UUID, list[_FakeBudget]] = {}

    def seed(self, user_id: uuid.UUID, category: str, monthly_limit: str) -> None:
        self._budgets.setdefault(user_id, []).append(
            _FakeBudget(category=category, monthly_limit=Decimal(monthly_limit))
        )

    async def list_for_user(self, user_id: uuid.UUID) -> list[_FakeBudget]:
        return list(self._budgets.get(user_id, []))


@dataclass
class _FakeSubscription:
    merchant: str
    amount_estimate: Decimal
    interval_days: int
    status: SubscriptionStatus
    first_detected_at: datetime


class FakeSubscriptionRepository:
    def __init__(self) -> None:
        self._subs: dict[uuid.UUID, list[_FakeSubscription]] = {}

    def seed(
        self,
        user_id: uuid.UUID,
        merchant: str,
        amount_estimate: str = "12.99",
        interval_days: int = 30,
        status: SubscriptionStatus = SubscriptionStatus.DETECTED,
        first_detected_at: datetime | None = None,
    ) -> None:
        self._subs.setdefault(user_id, []).append(
            _FakeSubscription(
                merchant=merchant,
                amount_estimate=Decimal(amount_estimate),
                interval_days=interval_days,
                status=status,
                first_detected_at=first_detected_at
                or datetime.now(timezone.utc),
            )
        )

    async def list_for_user(
        self, user_id: uuid.UUID, include_dismissed: bool = False
    ) -> list[_FakeSubscription]:
        subs = self._subs.get(user_id, [])
        if include_dismissed:
            return list(subs)
        return [s for s in subs if s.status == SubscriptionStatus.DETECTED]


class FakeTransactionRepository:
    """Same shape as test_spending_insights_handler.py's fake -- a flat
    list of (user_id, category, amount, txn_date) rows, aggregated by
    sum_by_category_for_user_in_range only (the one method this handler
    calls, for both the budget-risk current-month sum and the
    spending-spike rolling-window sums)."""

    def __init__(self) -> None:
        self.rows: list[tuple[uuid.UUID, str, Decimal, date]] = []

    def seed(self, user_id: uuid.UUID, category: str, amount: str, txn_date: date) -> None:
        self.rows.append((user_id, category, Decimal(amount), txn_date))

    async def sum_by_category_for_user_in_range(
        self, user_id: uuid.UUID, start_date: date, end_date: date
    ) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = {}
        for row_user_id, category, amount, txn_date in self.rows:
            if row_user_id != user_id or not (start_date <= txn_date < end_date):
                continue
            totals[category] = totals.get(category, Decimal("0")) + amount
        return totals


class FakeFollowThroughRepository:
    """FINTRACK-27. Minimal fake -- these pre-FINTRACK-27 tests never seed
    follow-through history, so list_recent_for_user_type_and_key always
    returns [], meaning RecommendationPrioritisationService's min-sample-
    size guard always keeps every candidate at normal priority. The other
    FollowThroughRepository methods aren't exercised by
    GetWeeklyRecommendationHandler and are omitted."""

    async def list_recent_for_user_type_and_key(
        self,
        user_id: uuid.UUID,
        recommendation_type: str,
        recommendation_key: str,
        limit: int = 10,
    ) -> list:
        return []


@pytest.fixture
def budgets() -> FakeBudgetRepository:
    return FakeBudgetRepository()


@pytest.fixture
def subscriptions() -> FakeSubscriptionRepository:
    return FakeSubscriptionRepository()


@pytest.fixture
def transactions() -> FakeTransactionRepository:
    return FakeTransactionRepository()


@pytest.fixture
def follow_through() -> FakeFollowThroughRepository:
    return FakeFollowThroughRepository()


def _handler(
    budgets, subscriptions, transactions, today: date, follow_through=None
) -> GetWeeklyRecommendationHandler:
    return GetWeeklyRecommendationHandler(
        budget_repository=budgets,
        subscription_repository=subscriptions,
        transaction_repository=transactions,
        follow_through_repository=follow_through or FakeFollowThroughRepository(),
        clock=lambda: today,
    )


# ---------------------------------------------------------------------------
# BA Gherkin scenario 1: user nearing a budget limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_at_80_pct_of_budget_gets_a_budget_risk_recommendation(
    budgets, subscriptions, transactions
) -> None:
    user_id = uuid.uuid4()
    today = date(2026, 7, 20)  # 10 days left in a 31-day July
    budgets.seed(user_id, "Dining", "100.00")
    transactions.seed(user_id, "Dining", "80.00", date(2026, 7, 5))  # exactly 80%

    handler = _handler(budgets, subscriptions, transactions, today)
    rec = await handler.handle(GetWeeklyRecommendationQuery(user_id=user_id))

    assert rec.type == RecommendationType.BUDGET_RISK
    assert rec.category == "Dining"
    assert "Dining" in rec.message
    assert "80%" in rec.message  # concrete action / reference is spelled out


# ---------------------------------------------------------------------------
# BA Gherkin scenario 2: no meaningful pattern -> neutral message, no
# fabricated claim
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_user_with_no_data_gets_neutral_encouraging_message(
    budgets, subscriptions, transactions
) -> None:
    user_id = uuid.uuid4()
    handler = _handler(budgets, subscriptions, transactions, date(2026, 7, 20))
    rec = await handler.handle(GetWeeklyRecommendationQuery(user_id=user_id))

    assert rec.type == RecommendationType.NEUTRAL
    assert rec.category is None
    assert rec.merchant is None
    # AC3: never fabricate a claim -- no digit (a $ amount or % figure)
    # appears in the neutral message.
    assert not any(ch.isdigit() for ch in rec.message)


# ---------------------------------------------------------------------------
# BA Gherkin scenario 3: newly detected subscription alone
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_subscription_alone_triggers_subscription_recommendation(
    budgets, subscriptions, transactions
) -> None:
    user_id = uuid.uuid4()
    today = date(2026, 7, 20)
    subscriptions.seed(
        user_id,
        merchant="NETFLIX.COM",
        first_detected_at=datetime(2026, 7, 18, tzinfo=timezone.utc),  # 2 days ago
    )

    handler = _handler(budgets, subscriptions, transactions, today)
    rec = await handler.handle(GetWeeklyRecommendationQuery(user_id=user_id))

    assert rec.type == RecommendationType.NEW_SUBSCRIPTION
    assert rec.merchant == "NETFLIX.COM"
    assert "NETFLIX.COM" in rec.message


@pytest.mark.asyncio
async def test_subscription_detected_outside_rolling_window_does_not_trigger(
    budgets, subscriptions, transactions
) -> None:
    """Gap-fill: a subscription detected 8 days ago is outside the
    7-day rolling window and must not be treated as 'new this week'."""
    user_id = uuid.uuid4()
    today = date(2026, 7, 20)
    subscriptions.seed(
        user_id,
        merchant="OLD NEWS INC",
        first_detected_at=datetime(2026, 7, 12, tzinfo=timezone.utc),  # 8 days ago
    )

    handler = _handler(budgets, subscriptions, transactions, today)
    rec = await handler.handle(GetWeeklyRecommendationQuery(user_id=user_id))

    assert rec.type == RecommendationType.NEUTRAL


@pytest.mark.asyncio
async def test_confirmed_subscription_does_not_count_as_new(
    budgets, subscriptions, transactions
) -> None:
    """Gap-fill: a CONFIRMED subscription is already-acknowledged, not
    'new,' even if it was first detected within the rolling window --
    only DETECTED-status rows count (get_weekly_recommendation.py's own
    documented rationale)."""
    user_id = uuid.uuid4()
    today = date(2026, 7, 20)
    subscriptions.seed(
        user_id,
        merchant="SPOTIFY",
        status=SubscriptionStatus.CONFIRMED,
        first_detected_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
    )

    handler = _handler(budgets, subscriptions, transactions, today)
    rec = await handler.handle(GetWeeklyRecommendationQuery(user_id=user_id))

    assert rec.type == RecommendationType.NEUTRAL


# ---------------------------------------------------------------------------
# BA Gherkin scenario 4: spending spike alone
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spending_spike_alone_triggers_spike_recommendation(
    budgets, subscriptions, transactions
) -> None:
    user_id = uuid.uuid4()
    today = date(2026, 7, 20)  # this week: Jul 14-20 inclusive

    # 4-week baseline (Jun 16 - Jul 14): $20/week average in "Shopping".
    for i in range(4):
        transactions.seed(user_id, "Shopping", "20.00", date(2026, 6, 17) + timedelta(days=7 * i))
    # This week: $50 -- 2.5x the $20 baseline average, clears the 1.5x bar.
    transactions.seed(user_id, "Shopping", "50.00", date(2026, 7, 18))

    handler = _handler(budgets, subscriptions, transactions, today)
    rec = await handler.handle(GetWeeklyRecommendationQuery(user_id=user_id))

    assert rec.type == RecommendationType.SPENDING_SPIKE
    assert rec.category == "Shopping"
    assert "Shopping" in rec.message


@pytest.mark.asyncio
async def test_no_baseline_history_never_fabricates_a_spike_claim(
    budgets, subscriptions, transactions
) -> None:
    """Gap-fill / AC3 guard: a category with spend this week but zero
    baseline history must not be called a 'spike' -- there's nothing to
    compare against, and get_weekly_recommendation.py's own docstring
    calls this out as exactly the kind of fabricated claim AC3
    forbids."""
    user_id = uuid.uuid4()
    today = date(2026, 7, 20)
    transactions.seed(user_id, "BrandNewCategory", "500.00", date(2026, 7, 18))

    handler = _handler(budgets, subscriptions, transactions, today)
    rec = await handler.handle(GetWeeklyRecommendationQuery(user_id=user_id))

    assert rec.type == RecommendationType.NEUTRAL


@pytest.mark.asyncio
async def test_spend_below_spike_multiplier_does_not_trigger(
    budgets, subscriptions, transactions
) -> None:
    """Gap-fill: routine week-to-week variance (below the 1.5x bar) must
    not be flagged -- avoids a false-positive spike."""
    user_id = uuid.uuid4()
    today = date(2026, 7, 20)
    for i in range(4):
        transactions.seed(user_id, "Shopping", "20.00", date(2026, 6, 17) + timedelta(days=7 * i))
    # 1.2x baseline -- under the 1.5x SPIKE_MULTIPLIER bar.
    transactions.seed(user_id, "Shopping", "24.00", date(2026, 7, 18))

    handler = _handler(budgets, subscriptions, transactions, today)
    rec = await handler.handle(GetWeeklyRecommendationQuery(user_id=user_id))

    assert rec.type == RecommendationType.NEUTRAL


# ---------------------------------------------------------------------------
# BA Gherkin scenario 5: multiple qualifying triggers -> exactly one
# recommendation, highest priority wins
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_risk_and_new_subscription_together_budget_risk_wins(
    budgets, subscriptions, transactions
) -> None:
    user_id = uuid.uuid4()
    today = date(2026, 7, 20)
    budgets.seed(user_id, "Dining", "100.00")
    transactions.seed(user_id, "Dining", "90.00", date(2026, 7, 5))
    subscriptions.seed(
        user_id, merchant="HULU", first_detected_at=datetime(2026, 7, 18, tzinfo=timezone.utc)
    )

    handler = _handler(budgets, subscriptions, transactions, today)
    rec = await handler.handle(GetWeeklyRecommendationQuery(user_id=user_id))

    # Exactly one recommendation object is returned by construction
    # (Recommendation is a single dataclass, not a list) -- the
    # assertion that matters is *which* one, per the documented priority.
    assert rec.type == RecommendationType.BUDGET_RISK
    assert rec.category == "Dining"


@pytest.mark.asyncio
async def test_new_subscription_and_spending_spike_together_subscription_wins(
    budgets, subscriptions, transactions
) -> None:
    """Gap-fill: the second priority tier, not covered by BA's own
    multi-trigger scenario (which only combines budget-risk +
    subscription) -- proves NEW_SUBSCRIPTION > SPENDING_SPIKE too, not
    just BUDGET_RISK > everything."""
    user_id = uuid.uuid4()
    today = date(2026, 7, 20)
    subscriptions.seed(
        user_id, merchant="DISNEY+", first_detected_at=datetime(2026, 7, 18, tzinfo=timezone.utc)
    )
    for i in range(4):
        transactions.seed(user_id, "Shopping", "20.00", date(2026, 6, 17) + timedelta(days=7 * i))
    transactions.seed(user_id, "Shopping", "50.00", date(2026, 7, 18))

    handler = _handler(budgets, subscriptions, transactions, today)
    rec = await handler.handle(GetWeeklyRecommendationQuery(user_id=user_id))

    assert rec.type == RecommendationType.NEW_SUBSCRIPTION
    assert rec.merchant == "DISNEY+"


# ---------------------------------------------------------------------------
# BA Gherkin scenario 6: scoped to the authenticated user only (IDOR at
# the handler layer)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommendation_never_reflects_another_users_data(
    budgets, subscriptions, transactions
) -> None:
    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    today = date(2026, 7, 20)

    # User B is deep over-budget and has a brand-new subscription --
    # none of this may leak into User A's neutral result.
    budgets.seed(user_b, "Dining", "100.00")
    transactions.seed(user_b, "Dining", "99.00", date(2026, 7, 5))
    subscriptions.seed(
        user_b, merchant="B-ONLY", first_detected_at=datetime(2026, 7, 18, tzinfo=timezone.utc)
    )

    handler = _handler(budgets, subscriptions, transactions, today)
    rec_a = await handler.handle(GetWeeklyRecommendationQuery(user_id=user_a))

    assert rec_a.type == RecommendationType.NEUTRAL
    assert rec_a.category is None
    assert rec_a.merchant is None
    assert "B-ONLY" not in rec_a.message


# ---------------------------------------------------------------------------
# Additional edge case: budget threshold boundary -- exactly at, and
# just under, BUDGET_RISK_THRESHOLD_PCT (80%).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_spend_just_under_threshold_does_not_trigger(
    budgets, subscriptions, transactions
) -> None:
    user_id = uuid.uuid4()
    today = date(2026, 7, 20)
    budgets.seed(user_id, "Dining", "100.00")
    transactions.seed(user_id, "Dining", "79.99", date(2026, 7, 5))

    handler = _handler(budgets, subscriptions, transactions, today)
    rec = await handler.handle(GetWeeklyRecommendationQuery(user_id=user_id))

    assert rec.type == RecommendationType.NEUTRAL


@pytest.mark.asyncio
async def test_multiple_budgets_at_risk_names_the_most_urgent_one(
    budgets, subscriptions, transactions
) -> None:
    """Gap-fill: when more than one budget independently qualifies as
    BUDGET_RISK, the handler must name exactly one -- and it should be
    the most urgent (highest percent-used), per
    get_weekly_recommendation.py's own sort-descending-by-percent-used
    comment."""
    user_id = uuid.uuid4()
    today = date(2026, 7, 20)
    budgets.seed(user_id, "Dining", "100.00")
    budgets.seed(user_id, "Groceries", "100.00")
    transactions.seed(user_id, "Dining", "82.00", date(2026, 7, 5))  # 82%
    transactions.seed(user_id, "Groceries", "95.00", date(2026, 7, 5))  # 95% -- more urgent

    handler = _handler(budgets, subscriptions, transactions, today)
    rec = await handler.handle(GetWeeklyRecommendationQuery(user_id=user_id))

    assert rec.type == RecommendationType.BUDGET_RISK
    assert rec.category == "Groceries"


@pytest.mark.asyncio
async def test_budget_with_no_monthly_limit_is_skipped_without_error(
    budgets, subscriptions, transactions
) -> None:
    """Gap-fill: defensive test for the handler's `if not budget.monthly_limit:
    continue` branch -- a zero/None limit must never cause a
    division-by-zero or false-positive trigger."""
    user_id = uuid.uuid4()
    today = date(2026, 7, 20)
    budgets.seed(user_id, "Dining", "0")
    transactions.seed(user_id, "Dining", "50.00", date(2026, 7, 5))

    handler = _handler(budgets, subscriptions, transactions, today)
    rec = await handler.handle(GetWeeklyRecommendationQuery(user_id=user_id))

    assert rec.type == RecommendationType.NEUTRAL


# ---------------------------------------------------------------------------
# Additional edge case: large dataset -- 1000+ transactions across many
# categories must not change the correctness of the priority resolution
# or blow up on aggregation (same "large dataset" gap-fill category the
# skill's Process step 1 calls out).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_remains_correct_with_a_large_transaction_volume(
    budgets, subscriptions, transactions
) -> None:
    user_id = uuid.uuid4()
    today = date(2026, 7, 20)
    budgets.seed(user_id, "Dining", "100.00")
    # 1000 one-dollar noise transactions across 5 unrelated categories --
    # none of them should be mistaken for the Dining budget spend.
    for i in range(1000):
        transactions.seed(user_id, f"Noise{i % 5}", "1.00", date(2026, 7, 3))
    transactions.seed(user_id, "Dining", "85.00", date(2026, 7, 5))

    handler = _handler(budgets, subscriptions, transactions, today)
    rec = await handler.handle(GetWeeklyRecommendationQuery(user_id=user_id))

    assert rec.type == RecommendationType.BUDGET_RISK
    assert rec.category == "Dining"
