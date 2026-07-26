"""Weekly Recommendation API endpoint. Story: FINTRACK-21.

Read-only. Requires authentication (get_current_user_id) and scopes
generation entirely to that user_id -- never a client-supplied
identifier, same IDOR-prevention discipline as insights.py/budgets.py.
There is no account-scoped path, body, or query parameter at all for a
caller to manipulate -- the only request input is the caller's own JWT.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends

from apps.api.application.dtos.recommendation_dtos import WeeklyRecommendationResponse
from apps.api.application.queries.get_weekly_recommendation import (
    GetWeeklyRecommendationHandler,
    GetWeeklyRecommendationQuery,
    Recommendation,
)
from apps.api.infrastructure.security.current_user import get_current_user_id
from apps.api.presentation.api.v1.dependencies import get_get_weekly_recommendation_handler

logger = logging.getLogger("fintrack.recommendations")
router = APIRouter(prefix="/api/v1/recommendations", tags=["recommendations"])


def _to_response(recommendation: Recommendation) -> WeeklyRecommendationResponse:
    return WeeklyRecommendationResponse(
        type=recommendation.type.value,
        message=recommendation.message,
        category=recommendation.category,
        merchant=recommendation.merchant,
    )


@router.get("/weekly", response_model=WeeklyRecommendationResponse)
async def get_weekly_recommendation(
    user_id: uuid.UUID = Depends(get_current_user_id),
    handler: GetWeeklyRecommendationHandler = Depends(get_get_weekly_recommendation_handler),
) -> WeeklyRecommendationResponse:
    recommendation = await handler.handle(GetWeeklyRecommendationQuery(user_id=user_id))
    logger.info(
        "weekly_recommendation_viewed",
        extra={"context": {"user_id": str(user_id), "type": recommendation.type.value}},
    )
    return _to_response(recommendation)
