"""Alerts API endpoints. Story: FINTRACK-22 (Threshold-Based Alerts).

Every endpoint requires authentication and scopes all data access to
user_id, never a client-supplied identifier -- same discipline as
transactions.py and budgets.py. Alerts themselves are only ever created
as a side effect of transaction creation (see the alert-evaluation call
in transactions.py's create_transaction), so this router only exposes
list and dismiss.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from apps.api.application.commands.dismiss_alert import DismissAlertCommand, DismissAlertHandler
from apps.api.application.dtos.alert_dtos import AlertListResponse, AlertResponse
from apps.api.application.queries.list_alerts import ListAlertsHandler, ListAlertsQuery
from apps.api.domain.repositories.alert_repository import AlertNotFoundError
from apps.api.infrastructure.security.current_user import get_current_user_id
from apps.api.presentation.api.v1.dependencies import (
    get_dismiss_alert_handler,
    get_list_alerts_handler,
)

logger = logging.getLogger("fintrack.alerts")
router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


def _to_response(alert) -> AlertResponse:
    return AlertResponse(
        id=alert.id,
        category=alert.category,
        alert_type=alert.alert_type.value,
        period_start=alert.period_start,
        threshold_pct=alert.threshold_pct,
        transaction_id=alert.transaction_id,
        fired_at=alert.fired_at,
        dismissed_at=alert.dismissed_at,
    )


@router.get("", response_model=AlertListResponse, status_code=status.HTTP_200_OK)
async def list_alerts(
    include_dismissed: bool = Query(default=False),
    user_id: uuid.UUID = Depends(get_current_user_id),
    handler: ListAlertsHandler = Depends(get_list_alerts_handler),
) -> AlertListResponse:
    alerts = await handler.handle(
        ListAlertsQuery(user_id=user_id, include_dismissed=include_dismissed)
    )
    return AlertListResponse(items=[_to_response(a) for a in alerts])


@router.post("/{alert_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_alert(
    alert_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    handler: DismissAlertHandler = Depends(get_dismiss_alert_handler),
) -> None:
    try:
        await handler.handle(DismissAlertCommand(alert_id=alert_id, user_id=user_id))
    except AlertNotFoundError:
        raise HTTPException(status_code=404, detail="Alert not found")
