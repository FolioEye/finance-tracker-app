"""Follow-Through Tracking API endpoints. Story: FINTRACK-23.

Every endpoint requires authentication and scopes all data access to
user_id, never a client-supplied identifier -- same discipline as
alerts.py/budgets.py. Records themselves are only ever created as a side
effect of GET /recommendations/weekly (see recommendations.py), so this
router only exposes acting on a record, listing history, and the rate.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from apps.api.application.commands.record_recommendation_action import (
    InvalidActionValueError,
    RecordRecommendationActionCommand,
    RecordRecommendationActionHandler,
)
from apps.api.application.dtos.follow_through_dtos import (
    FollowThroughHistoryResponse,
    FollowThroughRateResponse,
    FollowThroughRecordResponse,
    RecordActionRequest,
)
from apps.api.application.queries.get_follow_through_rate import (
    GetFollowThroughRateHandler,
    GetFollowThroughRateQuery,
)
from apps.api.application.queries.list_follow_through_history import (
    ListFollowThroughHistoryHandler,
    ListFollowThroughHistoryQuery,
)
from apps.api.domain.models.follow_through_record import FollowThroughRecord
from apps.api.domain.repositories.follow_through_repository import FollowThroughRecordNotFoundError
from apps.api.infrastructure.security.current_user import get_current_user_id
from apps.api.presentation.api.v1.dependencies import (
    get_get_follow_through_rate_handler,
    get_list_follow_through_history_handler,
    get_record_recommendation_action_handler,
)

logger = logging.getLogger("fintrack.follow_through")
router = APIRouter(prefix="/api/v1/follow-through", tags=["follow-through"])


def _to_response(record: FollowThroughRecord) -> FollowThroughRecordResponse:
    return FollowThroughRecordResponse(
        id=record.id,
        period_start=record.period_start,
        recommendation_type=record.recommendation_type,
        status=record.status.value,
        created_at=record.created_at,
        actioned_at=record.actioned_at,
    )


@router.post("/{record_id}/actions", status_code=status.HTTP_204_NO_CONTENT)
async def record_action(
    record_id: uuid.UUID,
    body: RecordActionRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    handler: RecordRecommendationActionHandler = Depends(get_record_recommendation_action_handler),
) -> None:
    try:
        await handler.handle(
            RecordRecommendationActionCommand(record_id=record_id, user_id=user_id, action=body.action)
        )
    except InvalidActionValueError:
        raise HTTPException(status_code=400, detail="Invalid action value")
    except FollowThroughRecordNotFoundError:
        raise HTTPException(status_code=404, detail="Follow-through record not found")


@router.get("", response_model=FollowThroughHistoryResponse, status_code=status.HTTP_200_OK)
async def list_follow_through_history(
    user_id: uuid.UUID = Depends(get_current_user_id),
    handler: ListFollowThroughHistoryHandler = Depends(get_list_follow_through_history_handler),
) -> FollowThroughHistoryResponse:
    records = await handler.handle(ListFollowThroughHistoryQuery(user_id=user_id))
    return FollowThroughHistoryResponse(items=[_to_response(r) for r in records])


@router.get("/rate", response_model=FollowThroughRateResponse, status_code=status.HTTP_200_OK)
async def get_follow_through_rate(
    user_id: uuid.UUID = Depends(get_current_user_id),
    handler: GetFollowThroughRateHandler = Depends(get_get_follow_through_rate_handler),
) -> FollowThroughRateResponse:
    result = await handler.handle(GetFollowThroughRateQuery(user_id=user_id))
    return FollowThroughRateResponse(
        done_count=result.done_count,
        dismissed_count=result.dismissed_count,
        ignored_count=result.ignored_count,
        rate_pct=result.rate_pct,
    )
