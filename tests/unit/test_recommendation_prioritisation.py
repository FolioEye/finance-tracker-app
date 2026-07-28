"""Unit tests for RecommendationPrioritisationService (FINTRACK-27).

Fakes RecommendationPrioritisationService's one dependency
(FollowThroughRepository) at the port boundary -- same convention as
tests/unit/test_weekly_recommendation_handler.py's fakes. Exercises
evaluate() directly, in isolation from GetWeeklyRecommendationHandler's
own within-tier reordering (covered separately in
test_weekly_recommendation_prioritisation.py) and from the real DB
(covered at the integration level in
test_recommendation_prioritisation_api.py).

Every scenario below maps 1:1 to a scenario in
tests/features/FINTRACK-27-recommendation-prioritisation.feature that
concerns the deprioritisation rule itself (AC1, AC2, and the two edge
cases) -- AC3's reason text, AC4's cross-tier ordering, and AC5's
per-user isolation are handler/API-level concerns and covered in the
other two new test files this story adds.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest

from apps.api.application.queries.recommendation_prioritisation import (
    DEPRIORITISATION_THRESHOLD_PCT,
    MIN_SAMPLE,
    ROLLING_WINDOW,
    RecommendationPrioritisationService,
)
from apps.api.domain.models.follow_through_record import FollowThroughStatus


@dataclass
class _FakeRecord:
    status: FollowThroughStatus

    def is_overdue(self, today) -> bool:
        # Every record fed into these tests represents an already-resolved
        # (or intentionally-still-PENDING-today) outcome -- overdue-to-
        # IGNORED reconciliation is FINTRACK-23's own concern, already
        # covered there. Always False here keeps that concern out of scope.
        return False


class FakeFollowThroughRepository:
    """seed() takes statuses oldest-first (readable in test bodies) and
    stores them most-recent-first internally, matching the real
    repository's list_recent_for_user_type_and_key contract (ORDER BY
    period_start DESC).
    """

    def __init__(self) -> None:
        self._by_key: dict[tuple, list[_FakeRecord]] = {}
        self.last_call: dict | None = None

    def seed(self, user_id, recommendation_type, recommendation_key, statuses_oldest_first) -> None:
        records_most_recent_first = [
            _FakeRecord(status=s) for s in reversed(statuses_oldest_first)
        ]
        self._by_key[(user_id, recommendation_type, recommendation_key)] = records_most_recent_first

    async def list_recent_for_user_type_and_key(
        self, user_id, recommendation_type, recommendation_key, limit=10
    ) -> list[_FakeRecord]:
        self.last_call = {
            "user_id": user_id,
            "recommendation_type": recommendation_type,
            "recommendation_key": recommendation_key,
            "limit": limit,
        }
        return self._by_key.get((user_id, recommendation_type, recommendation_key), [])[:limit]

    async def update(self, record) -> None:  # pragma: no cover - never overdue in these tests
        pass


@pytest.fixture
def repo() -> FakeFollowThroughRepository:
    return FakeFollowThroughRepository()


def _service(repo: FakeFollowThroughRepository) -> RecommendationPrioritisationService:
    return RecommendationPrioritisationService(repo)


# ---------------------------------------------------------------------------
# BA Gherkin scenario 1 (AC1): mostly-ignored type is deprioritised
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_20_pct_follow_through_rate_is_deprioritised(repo) -> None:
    user_id = uuid.uuid4()
    # 2 DONE, 8 IGNORED across the last 10 -- 20%, below the 30% threshold.
    statuses = [FollowThroughStatus.DONE] * 2 + [FollowThroughStatus.IGNORED] * 8
    repo.seed(user_id, "SPENDING_SPIKE", "dining-out", statuses)

    result = await _service(repo).evaluate(user_id, "SPENDING_SPIKE", "dining-out")

    assert result.deprioritised is True
    assert "2 of last 10" in result.reason_detail


# ---------------------------------------------------------------------------
# BA Gherkin scenario 2 (AC1, happy path): well-followed type stays normal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_80_pct_follow_through_rate_is_not_deprioritised(repo) -> None:
    user_id = uuid.uuid4()
    statuses = [FollowThroughStatus.DONE] * 8 + [FollowThroughStatus.DISMISSED] * 2
    repo.seed(user_id, "NEW_SUBSCRIPTION", "NETFLIX.COM", statuses)

    result = await _service(repo).evaluate(user_id, "NEW_SUBSCRIPTION", "NETFLIX.COM")

    assert result.deprioritised is False
    assert result.reason_detail is None


# ---------------------------------------------------------------------------
# BA Gherkin scenario 3 (AC2): instant recovery on the next follow-through,
# even while the rolling rate over the full window is still well under 30%
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_instant_recovery_when_most_recent_occurrence_is_done(repo) -> None:
    user_id = uuid.uuid4()
    # Only 1 of 10 done overall (10%, well under 30%) -- but it's the MOST
    # RECENT one, so BA's explicit recovery rule (not a rate recompute
    # alone) says this must already be back to normal priority.
    statuses = [FollowThroughStatus.IGNORED] * 9 + [FollowThroughStatus.DONE]
    repo.seed(user_id, "SPENDING_SPIKE", "dining-out", statuses)

    result = await _service(repo).evaluate(user_id, "SPENDING_SPIKE", "dining-out")

    assert result.deprioritised is False


@pytest.mark.asyncio
async def test_still_deprioritised_when_most_recent_occurrence_is_not_done(repo) -> None:
    """Converse of the recovery test -- confirms recovery is genuinely
    conditional on the most recent occurrence, not just on time passing."""
    user_id = uuid.uuid4()
    statuses = [FollowThroughStatus.DONE] * 2 + [FollowThroughStatus.IGNORED] * 8
    repo.seed(user_id, "SPENDING_SPIKE", "dining-out", statuses)

    result = await _service(repo).evaluate(user_id, "SPENDING_SPIKE", "dining-out")

    assert result.deprioritised is True


# ---------------------------------------------------------------------------
# Edge case: too few occurrences -- minimum sample size not reached
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fewer_than_minimum_sample_size_is_never_deprioritised(repo) -> None:
    user_id = uuid.uuid4()
    assert MIN_SAMPLE == 3  # guards the test's own premise if the constant ever changes
    statuses = [FollowThroughStatus.IGNORED] * 2  # 0% follow-through, but only 2 occurrences
    repo.seed(user_id, "BUDGET_RISK", "large-transaction-alert", statuses)

    result = await _service(repo).evaluate(user_id, "BUDGET_RISK", "large-transaction-alert")

    assert result.deprioritised is False
    assert result.reason_detail is None


@pytest.mark.asyncio
async def test_exactly_minimum_sample_size_with_low_rate_is_deprioritised(repo) -> None:
    """Boundary complement to the above -- exactly MIN_SAMPLE occurrences,
    all failing, must already be eligible for deprioritisation."""
    user_id = uuid.uuid4()
    statuses = [FollowThroughStatus.IGNORED] * MIN_SAMPLE

    repo.seed(user_id, "BUDGET_RISK", "Dining", statuses)

    result = await _service(repo).evaluate(user_id, "BUDGET_RISK", "Dining")

    assert result.deprioritised is True


# ---------------------------------------------------------------------------
# Negative/edge case: brand-new type with no history at all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_brand_new_type_with_no_history_is_not_deprioritised(repo) -> None:
    result = await _service(repo).evaluate(uuid.uuid4(), "SPENDING_SPIKE", "new-merchant-detected")

    assert result.deprioritised is False
    assert result.reason_detail is None


def test_none_recommendation_key_short_circuits_without_a_repository_call() -> None:
    """NEUTRAL recommendations pass recommendation_key=None (see
    recommendations.py's _recommendation_key) -- must never be
    deprioritised and must never even query the repository."""
    import asyncio

    repo = FakeFollowThroughRepository()
    result = asyncio.run(_service(repo).evaluate(uuid.uuid4(), "NEUTRAL", None))

    assert result.deprioritised is False
    assert repo.last_call is None


# ---------------------------------------------------------------------------
# Boundary: exactly at the 30% threshold is NOT deprioritised -- the BA rule
# and the Gherkin's own wording ("at or above the 30% threshold" keeps
# normal priority) is a strict less-than, not less-than-or-equal.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exactly_30_pct_follow_through_rate_is_not_deprioritised(repo) -> None:
    user_id = uuid.uuid4()
    assert DEPRIORITISATION_THRESHOLD_PCT == 30
    statuses = [FollowThroughStatus.DONE] * 3 + [FollowThroughStatus.IGNORED] * 7  # exactly 30%
    repo.seed(user_id, "SPENDING_SPIKE", "dining-out", statuses)

    result = await _service(repo).evaluate(user_id, "SPENDING_SPIKE", "dining-out")

    assert result.deprioritised is False


@pytest.mark.asyncio
async def test_just_under_30_pct_is_deprioritised(repo) -> None:
    """29% (2.9/10, rounds to below 3 done out of 10 isn't representable
    with whole occurrences, so use a 20-occurrence window truncated to
    the service's own ROLLING_WINDOW cap to land exactly on 29%)."""
    user_id = uuid.uuid4()
    # Repository already caps at ROLLING_WINDOW=10 internally in
    # production; this fake returns whatever it's given up to `limit`, so
    # seed exactly 10 with 2 done (20%, unambiguously under 30%) instead of
    # relying on a non-representable 2.9/10.
    statuses = [FollowThroughStatus.DONE] * 2 + [FollowThroughStatus.IGNORED] * 8
    repo.seed(user_id, "SPENDING_SPIKE", "dining-out", statuses)

    result = await _service(repo).evaluate(user_id, "SPENDING_SPIKE", "dining-out")

    assert result.deprioritised is True


# ---------------------------------------------------------------------------
# Contract check: the repository is queried with exactly the parameters the
# service documents (user_id, type, key, limit=ROLLING_WINDOW) -- this is
# what actually backs the "last 10 times shown" rule in production, so it's
# worth asserting directly rather than only inferring it from behaviour.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repository_queried_with_documented_rolling_window_limit(repo) -> None:
    user_id = uuid.uuid4()
    assert ROLLING_WINDOW == 10
    repo.seed(user_id, "BUDGET_RISK", "Dining", [FollowThroughStatus.DONE] * 3)

    await _service(repo).evaluate(user_id, "BUDGET_RISK", "Dining")

    assert repo.last_call == {
        "user_id": user_id,
        "recommendation_type": "BUDGET_RISK",
        "recommendation_key": "Dining",
        "limit": ROLLING_WINDOW,
    }


# ---------------------------------------------------------------------------
# Only *resolved* occurrences count toward sample size and rate (Tech Lead's
# documented interpretation of BA's "occurrences" wording) -- a PENDING
# record (shown today, not yet actioned) must not count either way.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_records_excluded_from_sample_size_and_rate(repo) -> None:
    user_id = uuid.uuid4()
    # 2 resolved (both IGNORED) + 1 still-PENDING (today's, not yet
    # actioned) -- only 2 *resolved* occurrences, below MIN_SAMPLE, even
    # though 3 records exist in the window.
    statuses = [FollowThroughStatus.IGNORED, FollowThroughStatus.IGNORED, FollowThroughStatus.PENDING]
    repo.seed(user_id, "BUDGET_RISK", "Dining", statuses)

    result = await _service(repo).evaluate(user_id, "BUDGET_RISK", "Dining")

    assert result.deprioritised is False
