"""Response DTOs for the spending insights API. Story: FINTRACK-19.

Read-only endpoint -- there is no request body DTO, only a bounded query
parameter (trend_months) validated directly on the router via FastAPI's
Query(ge=1, le=24), same as this project's other simple bounded params.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel


class CategoryBreakdownItemResponse(BaseModel):
    category: str
    total: str


class MonthlyTrendItemResponse(BaseModel):
    # "YYYY-MM" -- pre-formatted server-side so the frontend never has to
    # zero-pad a month integer itself.
    month: str
    total: str


class SpendingInsightsResponse(BaseModel):
    current_month_total: str
    by_category: list[CategoryBreakdownItemResponse]
    monthly_trend: list[MonthlyTrendItemResponse]


def _decimal_to_str(value: Decimal) -> str:
    return str(value)
