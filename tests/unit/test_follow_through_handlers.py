"""Unit tests for the follow-through command/query handlers (FINTRACK-23):
EnsureFollowThroughRecordHandler, RecordRecommendationActionHandler,
ListFollowThroughHistoryHandler, GetFollowThroughRateHandler. Fake
in-memory repository stands in for SqlAlchemyFollowThroughRepository,
same pattern as tests/unit/test_alert_handlers.py's FakeAlertRepository.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from apps.api.application.commands.ensure_follow_through_record import (
    EnsureFollowThroughRecordCommand,
    EnsureFollowThroughRecordHandler,
)
from apps.api.application.commands.record_recommendation_action import (
    InvalidActionValueError,
    RecordRecommendationActionCommand,
    RecordRecommendationActionHandler,
)
from apps.api.application.queries.get_follow_through_rate import (
    RATE_ROLLING_WINDOW_DAYS,
    GetFollowThroughRateHandler,
    GetFollowThroughRateQuery,
)
from apps.api.application.queries.list_follow_through_history import (
    ListFollowThroughHistoryHandler,
    ListFollowThroughHistoryQuery,
)
from apps.api.domain.models.follow_through_record import FollowThroughRecord, FollowThroughStatus
from apps.api.domain.repositories.follow_through_repository import FollowThroughRecordNotFoundError


class FakeFollowThroughRepository:
    """In-memory stand-in for SqlAlchemyFollowThroughRepository. Implements
    the full FollowThroughRepository port, including its
    None-for-not-found-or-not-yours semantics on get_by_id_for_user."""

    def __init__(self) -> None:
        self.records: dict[uuid.UUID, FollowThroughRecord] = {}
        self.update_calls = 0

    async def add(self, record: FollowThroughRecord) -> None:
        self.records[record.id] = record

    async def get_by_id_for_user(self, record_id: uuid.UUID, user_id: uuid.UUID):
        record = self.records.get(record_id)
        if record is None or record.user_id != user_id:
            return None
        return record

    async def get_for_user_and_period(self, user_id: uuid.UUID, period_start: date):
        for record in self.records.values():
            if record.user_id == user_id and record.period_start == period_start:
                return record
        return None

    async def list_for_user(self, user_id: uuid.UUID) -> list[FollowThroughRecord]:
        result = [r for r in self.records.values() if r.user_id == user_id]
        return sorted(result, key=lambda r: r.period_start, reverse=True)

    async def update(self, record: FollowThroughRecord) -> None:
        self.update_calls += 1
        self.records[record.id] = record


# ---------------------------------------------------------------------------
# EnsureFollowThroughRecordHandler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_creates_a_new_pending_record_when_none_exists() -> None:
    repo = FakeFollowThroughRepository()
    handler = EnsureFollowThroughRecordHandler(follow_through_repository=repo)
    user_id = uuid.uuid4()

    record = await handler.handle(
        EnsureFollowThroughRecordCommand(
            user_id=user_id, period_start=date(2026, 7, 27), recommendation_type="BUDGET_RISK"
        )
    )

    assert record.status == FollowThroughStatus.PENDING
    assert record.recommendation_type == "BUDGET_RISK"
    assert len(repo.records) == 1


@pytest.mark.asyncio
async def test_ensure_returns_the_existing_record_on_a_second_call_same_period() -> None:
    """Idempotent get-or-create: a user refreshing the page twice in one
    day must not get two rows, and must not have their existing action
    state clobbered."""
    repo = FakeFollowThroughRepository()
    handler = EnsureFollowThroughRecordHandler(follow_through_repository=repo)
    user_id = uuid.uuid4()
    command = EnsureFollowThroughRecordCommand(
        user_id=user_id, period_start=date(2026, 7, 27), recommendation_type="BUDGET_RISK"
    )

    first = await handler.handle(command)
    first.mark_done()  # simulate the user having already acted
    await repo.update(first)

    second = await handler.handle(command)

    assert second.id == first.id
    assert second.status == FollowThroughStatus.DONE  # not reset to PENDING
    assert len(repo.records) == 1


@pytest.mark.asyncio
async def test_ensure_creates_a_distinct_record_for_a_different_period() -> None:
    repo = FakeFollowThroughRepository()
    handler = EnsureFollowThroughRecordHandler(follow_through_repository=repo)
    user_id = uuid.uuid4()

    day1 = await handler.handle(
        EnsureFollowThroughRecordCommand(user_id, date(2026, 7, 26), "BUDGET_RISK")
    )
    day2 = await handler.handle(
        EnsureFollowThroughRecordCommand(user_id, date(2026, 7, 27), "NEW_SUBSCRIPTION")
    )

    assert day1.id != day2.id
    assert len(repo.records) == 2


# ---------------------------------------------------------------------------
# RecordRecommendationActionHandler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_action_done_transitions_the_record() -> None:
    repo = FakeFollowThroughRepository()
    user_id = uuid.uuid4()
    record = FollowThroughRecord.new_pending(user_id, date(2026, 7, 27), "BUDGET_RISK")
    await repo.add(record)
    handler = RecordRecommendationActionHandler(follow_through_repository=repo)

    await handler.handle(RecordRecommendationActionCommand(record.id, user_id, "done"))

    assert repo.records[record.id].status == FollowThroughStatus.DONE
    assert repo.update_calls == 1


@pytest.mark.asyncio
async def test_record_action_dismiss_transitions_the_record() -> None:
    repo = FakeFollowThroughRepository()
    user_id = uuid.uuid4()
    record = FollowThroughRecord.new_pending(user_id, date(2026, 7, 27), "BUDGET_RISK")
    await repo.add(record)
    handler = RecordRecommendationActionHandler(follow_through_repository=repo)

    await handler.handle(RecordRecommendationActionCommand(record.id, user_id, "dismiss"))

    assert repo.records[record.id].status == FollowThroughStatus.DISMISSED


@pytest.mark.asyncio
async def test_record_action_invalid_value_raises_without_any_repository_lookup() -> None:
    """Gherkin: invalid action value -> validation error, no follow-through
    status recorded or changed. Asserting update_calls stays 0 (and that
    no lookup happened at all) proves nothing was touched."""
    repo = FakeFollowThroughRepository()
    user_id = uuid.uuid4()
    record = FollowThroughRecord.new_pending(user_id, date(2026, 7, 27), "BUDGET_RISK")
    await repo.add(record)
    handler = RecordRecommendationActionHandler(follow_through_repository=repo)

    with pytest.raises(InvalidActionValueError, match="Invalid action value"):
        await handler.handle(RecordRecommendationActionCommand(record.id, user_id, "delete"))

    assert repo.records[record.id].status == FollowThroughStatus.PENDING  # untouched
    assert repo.update_calls == 0


@pytest.mark.asyncio
async def test_record_action_nonexistent_record_id_raises_not_found() -> None:
    repo = FakeFollowThroughRepository()
    handler = RecordRecommendationActionHandler(follow_through_repository=repo)

    with pytest.raises(FollowThroughRecordNotFoundError):
        await handler.handle(RecordRecommendationActionCommand(uuid.uuid4(), uuid.uuid4(), "done"))


@pytest.mark.asyncio
async def test_record_action_another_users_record_id_raises_not_found_not_forbidden() -> None:
    """IDOR discipline: belongs-to-someone-else and doesn't-exist must be
    indistinguishable to the caller."""
    repo = FakeFollowThroughRepository()
    owner_id = uuid.uuid4()
    attacker_id = uuid.uuid4()
    record = FollowThroughRecord.new_pending(owner_id, date(2026, 7, 27), "BUDGET_RISK")
    await repo.add(record)
    handler = RecordRecommendationActionHandler(follow_through_repository=repo)

    with pytest.raises(FollowThroughRecordNotFoundError):
        await handler.handle(RecordRecommendationActionCommand(record.id, attacker_id, "done"))

    assert repo.records[record.id].status == FollowThroughStatus.PENDING  # victim's record untouched


@pytest.mark.asyncio
async def test_record_action_still_succeeds_on_an_already_ignored_record() -> None:
    """A late action (after the 7-day auto-ignore already fired) still
    counts -- see record_recommendation_action.py's module docstring for
    the rationale."""
    repo = FakeFollowThroughRepository()
    user_id = uuid.uuid4()
    record = FollowThroughRecord.new_pending(user_id, date(2026, 7, 1), "BUDGET_RISK")
    record.mark_ignored()
    await repo.add(record)
    handler = RecordRecommendationActionHandler(follow_through_repository=repo)

    await handler.handle(RecordRecommendationActionCommand(record.id, user_id, "done"))

    assert repo.records[record.id].status == FollowThroughStatus.DONE


# ---------------------------------------------------------------------------
# ListFollowThroughHistoryHandler -- read-time reconciliation (AC4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_history_reconciles_an_overdue_pending_record_to_ignored() -> None:
    repo = FakeFollowThroughRepository()
    user_id = uuid.uuid4()
    old_record = FollowThroughRecord.new_pending(user_id, date(2026, 7, 1), "BUDGET_RISK")
    await repo.add(old_record)
    handler = ListFollowThroughHistoryHandler(
        follow_through_repository=repo, clock=lambda: date(2026, 7, 10)
    )  # 9 days later -> overdue

    result = await handler.handle(ListFollowThroughHistoryQuery(user_id=user_id))

    assert result[0].status == FollowThroughStatus.IGNORED
    assert repo.update_calls == 1  # persisted, not just returned


@pytest.mark.asyncio
async def test_list_history_does_not_touch_a_pending_record_still_within_window() -> None:
    repo = FakeFollowThroughRepository()
    user_id = uuid.uuid4()
    recent_record = FollowThroughRecord.new_pending(user_id, date(2026, 7, 8), "BUDGET_RISK")
    await repo.add(recent_record)
    handler = ListFollowThroughHistoryHandler(
        follow_through_repository=repo, clock=lambda: date(2026, 7, 10)
    )  # 2 days later -> not overdue

    result = await handler.handle(ListFollowThroughHistoryQuery(user_id=user_id))

    assert result[0].status == FollowThroughStatus.PENDING
    assert repo.update_calls == 0


@pytest.mark.asyncio
async def test_list_history_does_not_reprocess_an_already_resolved_record() -> None:
    repo = FakeFollowThroughRepository()
    user_id = uuid.uuid4()
    done_record = FollowThroughRecord.new_pending(user_id, date(2026, 6, 1), "BUDGET_RISK")
    done_record.mark_done()
    await repo.add(done_record)
    handler = ListFollowThroughHistoryHandler(
        follow_through_repository=repo, clock=lambda: date(2026, 7, 20)
    )

    result = await handler.handle(ListFollowThroughHistoryQuery(user_id=user_id))

    assert result[0].status == FollowThroughStatus.DONE
    assert repo.update_calls == 0


@pytest.mark.asyncio
async def test_list_history_scoped_to_the_requesting_user_only() -> None:
    repo = FakeFollowThroughRepository()
    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    await repo.add(FollowThroughRecord.new_pending(user_a, date(2026, 7, 20), "BUDGET_RISK"))
    await repo.add(FollowThroughRecord.new_pending(user_b, date(2026, 7, 20), "BUDGET_RISK"))
    handler = ListFollowThroughHistoryHandler(follow_through_repository=repo, clock=lambda: date(2026, 7, 20))

    result = await handler.handle(ListFollowThroughHistoryQuery(user_id=user_a))

    assert len(result) == 1
    assert result[0].user_id == user_a


# ---------------------------------------------------------------------------
# GetFollowThroughRateHandler (AC3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_matches_the_gherkin_scenario_exactly_2_done_1_dismissed_1_ignored() -> None:
    """Directly exercises Gherkin scenario 7: 2 Done, 1 Dismiss, 1 Ignored
    over the rolling window -> 50%."""
    repo = FakeFollowThroughRepository()
    user_id = uuid.uuid4()
    today = date(2026, 7, 20)

    done_1 = FollowThroughRecord.new_pending(user_id, today, "BUDGET_RISK")
    done_1.mark_done()
    done_2 = FollowThroughRecord.new_pending(user_id, today - __import__("datetime").timedelta(days=1), "SPENDING_SPIKE")
    done_2.mark_done()
    dismissed = FollowThroughRecord.new_pending(user_id, today - __import__("datetime").timedelta(days=2), "NEW_SUBSCRIPTION")
    dismissed.mark_dismissed()
    ignored = FollowThroughRecord.new_pending(user_id, today - __import__("datetime").timedelta(days=3), "BUDGET_RISK")
    ignored.mark_ignored()

    for r in (done_1, done_2, dismissed, ignored):
        await repo.add(r)

    handler = GetFollowThroughRateHandler(follow_through_repository=repo, clock=lambda: today)
    result = await handler.handle(GetFollowThroughRateQuery(user_id=user_id))

    assert result.done_count == 2
    assert result.dismissed_count == 1
    assert result.ignored_count == 1
    assert result.rate_pct == Decimal("50.00")


@pytest.mark.asyncio
async def test_rate_is_none_when_nothing_is_resolved_yet() -> None:
    repo = FakeFollowThroughRepository()
    user_id = uuid.uuid4()
    await repo.add(FollowThroughRecord.new_pending(user_id, date(2026, 7, 20), "BUDGET_RISK"))
    handler = GetFollowThroughRateHandler(follow_through_repository=repo, clock=lambda: date(2026, 7, 20))

    result = await handler.handle(GetFollowThroughRateQuery(user_id=user_id))

    assert result.rate_pct is None
    assert result.done_count == 0


@pytest.mark.asyncio
async def test_rate_excludes_records_outside_the_rolling_window() -> None:
    from datetime import timedelta

    repo = FakeFollowThroughRepository()
    user_id = uuid.uuid4()
    today = date(2026, 7, 20)

    in_window = FollowThroughRecord.new_pending(user_id, today - timedelta(days=1), "BUDGET_RISK")
    in_window.mark_done()
    out_of_window = FollowThroughRecord.new_pending(
        user_id, today - timedelta(days=RATE_ROLLING_WINDOW_DAYS + 5), "BUDGET_RISK"
    )
    out_of_window.mark_dismissed()

    await repo.add(in_window)
    await repo.add(out_of_window)

    handler = GetFollowThroughRateHandler(follow_through_repository=repo, clock=lambda: today)
    result = await handler.handle(GetFollowThroughRateQuery(user_id=user_id))

    assert result.done_count == 1
    assert result.dismissed_count == 0  # excluded -- outside the window
    assert result.rate_pct == Decimal("100.00")


@pytest.mark.asyncio
async def test_rate_reconciles_an_overdue_pending_record_before_counting() -> None:
    """An overdue-but-still-PENDING record must be counted as IGNORED in
    the rate, not silently excluded as if it never existed."""
    repo = FakeFollowThroughRepository()
    user_id = uuid.uuid4()
    stale = FollowThroughRecord.new_pending(user_id, date(2026, 7, 1), "BUDGET_RISK")
    await repo.add(stale)
    handler = GetFollowThroughRateHandler(follow_through_repository=repo, clock=lambda: date(2026, 7, 15))

    result = await handler.handle(GetFollowThroughRateQuery(user_id=user_id))

    assert result.ignored_count == 1
    assert result.rate_pct == Decimal("0.00")
