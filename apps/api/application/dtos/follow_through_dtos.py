"""Request/response DTOs for the follow-through API. Story: FINTRACK-23."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class RecordActionRequest(BaseModel):
    # Deliberately `str`, not Literal["done", "dismiss"] -- validation is
    # done explicitly in RecordRecommendationActionHandler so the exact
    # rejection message ("Invalid action value") is controlled by the
    # application layer, not Pydantic's generic enum-validation error,
    # and is unit-testable without going through FastAPI at all.
    action: str


class FollowThroughRecordResponse(BaseModel):
    id: uuid.UUID
    period_start: date
    recommendation_type: str
    status: str
    created_at: datetime
    actioned_at: Optional[datetime]

    model_config = {"from_attributes": True}


class FollowThroughHistoryResponse(BaseModel):
    items: list[FollowThroughRecordResponse]


class FollowThroughRateResponse(BaseModel):
    done_count: int
    dismissed_count: int
    ignored_count: int
    rate_pct: Optional[Decimal]
