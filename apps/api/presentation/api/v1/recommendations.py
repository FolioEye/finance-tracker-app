"""Weekly Recommendation API endpoint. Story: FINTRACK-21, extended by
FINTRACK-23.

Read-only. Requires authentication (get_current_user_id) and scopes
generation entirely to that user_id -- never a client-supplied
identifier, same IDOR-prevention discipline as insights.py/budgets.py.
There is no account-scoped path, body, or query parameter at all for a
caller to manipulate -- the only request input is the caller's own JWT.

FINTRACK-23 wiring: after computing the recommendation, this route
ensures a FollowThroughRecord exists for today (idempotent get-or-create)
and returns its id so the client has something to act against at
POST /api/v1/follow-through/{id}/actions. GetWeeklyRecommendationHandler
itself is completely untouched by this -- the orchestration lives here in
the presentation layer only, per the architecture decision documented in
domain.models.follow_through_record.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date

from fastapi import APIRouter, Depends

from apps.api.application.commands.ensure_follow_through_record import (
    EnsureFollowThroughRecordCommand,
    EnsureFollowThroughRecordHandler,
)
from apps.api.application.dtos.recommendation_dtos import WeeklyRecommendationResponse
from apps.api.application.queries.get_weekly_recommendation import (
    GetWeeklyRecommendationHandler,
    GetWeeklyRecommendationQuery,
    Recommendation,
)
from apps.api.domain.models.follow_through_record import FollowThroughRecord
from apps.api.infrastructure.security.current_user import get_current_user_id
from apps.api.presentation.api.v1.dependencies import (
    get_ensure_follow_through_record_handler,
    get_get_weekly_recommendation_handler,
)

logger = logging.getLogger("fintrack.recommendations")
router = APIRouter(prefix="/api/v1/recommendations", tags=["recommendations"])


def _to_response(
    recommendation: Recommendation, follow_through_record: FollowThroughRecord
) -> WeeklyRecommendationResponse:
    return WeeklyRecommendationResponse(
        type=recommendation.type.value,
        message=recommendation.message,
        category=recommendation.category,
        merchant=recommendation.merchant,
        follow_through_record_id=follow_through_record.id,
    )


@router.get("/weekly", response_model=WeeklyRecommendationResponse)
async def get_weekly_recommendation(
    user_id: uuid.UUID = Depends(get_current_user_id),
    handler: GetWeeklyRecommendationHandler = Depends(get_get_weekly_recommendation_handler),
    ensure_follow_through: EnsureFollowThroughRecordHandler = Depends(
        get_ensure_follow_through_record_handler
    ),
) -> WeeklyRecommendationResponse:
    recommendation = await handler.handle(GetWeeklyRecommendationQuery(user_id=user_id))
    follow_through_record = await ensure_follow_through.handle(
        EnsureFollowThroughRecordCommand(
            user_id=user_id,
            period_start=date.today(),
            recommendation_type=recommendation.type.value,
        )
    )
    logger.info(
        "weekly_recommendation_viewed",
        extra={"context": {"user_id": str(user_id), "type": recommendation.type.value}},
    )
    return _to_response(recommendation, follow_through_record)
