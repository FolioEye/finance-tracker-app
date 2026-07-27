"""AlertJustification domain entity. Story: FINTRACK-25 (Alert
Justification Feedback Loop).

Deliberately NOT a per-alert flag on the Alert row itself (unlike
dismissed_at) -- AC2/AC3 require the suppression effect to apply to
*future* transactions in the same category, not just to the one alert
being justified. One row per (user_id, category): the highest amount the
user has ever explicitly justified as "expected" for that category.
Justifying a smaller amount than the current ceiling is a no-op (AC2's
"is not lowered" -- the ceiling only ever rises, via
raise_ceiling_if_higher()).

Deliberately independent of Alert.dismiss() (AC5/AC6): dismissing an
alert never creates or touches an AlertJustification row, and justifying
an alert never touches dismissed_at -- these are two orthogonal actions
on two different tables/rows.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal


@dataclass
class AlertJustification:
    id: uuid.UUID
    user_id: uuid.UUID
    category: str
    ceiling_amount: Decimal
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def new(user_id: uuid.UUID, category: str, ceiling_amount: Decimal) -> "AlertJustification":
        now = datetime.now(timezone.utc)
        return AlertJustification(
            id=uuid.uuid4(),
            user_id=user_id,
            category=category,
            ceiling_amount=ceiling_amount,
            created_at=now,
            updated_at=now,
        )

    def raise_ceiling_if_higher(self, amount: Decimal) -> bool:
        """AC2: the ceiling only ever rises, never falls. Returns True if
        this call actually changed the ceiling, so the caller knows
        whether a persistence update is needed."""
        if amount > self.ceiling_amount:
            self.ceiling_amount = amount
            self.updated_at = datetime.now(timezone.utc)
            return True
        return False
