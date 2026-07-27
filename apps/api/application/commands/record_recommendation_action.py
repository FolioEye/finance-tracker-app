"""RecordRecommendationActionCommand + handler. Story: FINTRACK-23 (AC1/AC2).

Validation happens here, not only at the Pydantic/FastAPI layer, so the
exact rejection behaviour (reject silently, no state change, precise
error text) is unit-testable independent of the HTTP framework -- same
discipline as CreateTransactionHandler's amount validation.

A late action is still accepted even if the record has already been
auto-marked IGNORED by the read-time reconciliation in
follow_through_reconciliation.py -- a user who shows up on day 9 and
clicks "Done" gets credit for a real action rather than being told
they're too late; only the terminal *status* changes, actioned_at always
reflects the real time of the actual user action.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from apps.api.domain.repositories.follow_through_repository import (
    FollowThroughRecordNotFoundError,
    FollowThroughRepository,
)

VALID_ACTIONS = frozenset({"done", "dismiss"})


class InvalidActionValueError(Exception):
    """Raised when `action` is anything other than "done" or "dismiss" --
    mapped to HTTP 400 with message "Invalid action value" at the API
    layer (AC negative scenario)."""


@dataclass(frozen=True)
class RecordRecommendationActionCommand:
    record_id: uuid.UUID
    user_id: uuid.UUID
    action: str


class RecordRecommendationActionHandler:
    def __init__(self, follow_through_repository: FollowThroughRepository) -> None:
        self._records = follow_through_repository

    async def handle(self, command: RecordRecommendationActionCommand) -> None:
        if command.action not in VALID_ACTIONS:
            # No record lookup at all for an invalid action -- nothing
            # should be recorded or changed, per the Gherkin scenario,
            # and this also avoids leaking "does this record_id exist"
            # information via a validation-error code path.
            raise InvalidActionValueError("Invalid action value")

        record = await self._records.get_by_id_for_user(command.record_id, command.user_id)
        if record is None:
            # Same one-error-for-both-cases shape as AlertNotFoundError:
            # covers both "doesn't exist" and "belongs to another user"
            # (the IDOR scenario) with an identical 404.
            raise FollowThroughRecordNotFoundError("Follow-through record not found")

        if command.action == "done":
            record.mark_done()
        else:
            record.mark_dismissed()

        await self._records.update(record)
