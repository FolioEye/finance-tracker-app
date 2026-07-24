"""Spending Insights Dashboard API endpoint. Story: FINTRACK-19.

Read-only. Requires authentication (get_current_user_id) and scopes the
aggregation entirely to that user_id -- never a client-supplied
identifier -- same IDOR-prevention discipline as budgets.py/
transactions.py. There is no account-scoped path or body parameter for a
caller to manipulate at all: the only request input is a bounded
trend_months query param.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Query

from apps.api.application.dtos.insights_dtos import (
    CategoryBreakdownItemResponse,
    MonthlyTrendItemResponse,
    SpendingInsightsResponse,
)
from apps.api.application.queries.get_spending_insights import (
    DEFAULT_TREND_MONTHS,
    GetSpendingInsightsHandler,
    GetSpendingInsightsQuery,
    SpendingInsights,
)
from apps.api.infrastructure.security.current_user import get_current_user_id
from apps.api.presentation.api.v1.dependencies import get_get_spending_insights_handler

logger = logging.getLogger("fintrack.insights")
router = APIRouter(prefix="/api/v1/insights", tags=["insights"])


def _to_response(insights: SpendingInsights) -> SpendingInsightsResponse:
    return SpendingInsightsResponse(
        current_month_total=str(insights.current_month_total),
        by_category=[
            CategoryBreakdownItemResponse(category=item.category, total=str(item.total))
            for item in insights.by_category
        ],
        monthly_trend=[
            MonthlyTrendItemResponse(
                month=f"{item.year:04d}-{item.month:02d}", total=str(item.total)
            )
            for item in insights.monthly_trend
        ],
    )


@router.get("/dashboard", response_model=SpendingInsightsResponse)
async def get_spending_insights_dashboard(
    trend_months: int = Query(default=DEFAULT_TREND_MONTHS, ge=1, le=24),
    user_id: uuid.UUID = Depends(get_current_user_id),
    handler: GetSpendingInsightsHandler = Depends(get_get_spending_insights_handler),
) -> SpendingInsightsResponse:
    insights = await handler.handle(
        GetSpendingInsightsQuery(user_id=user_id, trend_months=trend_months)
    )
    logger.info(
        "spending_insights_viewed",
        extra={"context": {"user_id": str(user_id), "trend_months": trend_months}},
    )
    return _to_response(insights)
