"""Response DTOs for the alerts API. Story: FINTRACK-22.

Read-only resource from the API's point of view -- alerts are only ever
created as a side effect of transaction evaluation, never via a direct
POST, so there's no CreateAlertRequest here.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class AlertResponse(BaseModel):
    id: uuid.UUID
    category: str
    alert_type: str
    period_start: date
    threshold_pct: Decimal | None
    transaction_id: uuid.UUID | None
    fired_at: datetime
    dismissed_at: datetime | None

    model_config = {"from_attributes": True}


class AlertListResponse(BaseModel):
    items: list[AlertResponse]
