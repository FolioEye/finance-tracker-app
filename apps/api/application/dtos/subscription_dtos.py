"""Response DTOs for the subscriptions API. Story: FINTRACK-18.

Read-only resource from the API's point of view for creation -- rows are
only ever created as a side effect of transaction detection, never via a
direct POST, so there's no CreateSubscriptionRequest here (mirrors
alert_dtos.py's rationale exactly).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class SubscriptionResponse(BaseModel):
    id: uuid.UUID
    merchant: str
    amount_estimate: Decimal
    interval_days: int
    occurrences: int
    status: str
    last_transaction_id: uuid.UUID
    first_detected_at: datetime
    last_seen_at: datetime

    model_config = {"from_attributes": True}


class SubscriptionListResponse(BaseModel):
    items: list[SubscriptionResponse]
