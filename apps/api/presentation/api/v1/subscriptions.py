"""Subscriptions API endpoints. Story: FINTRACK-18 (Subscription /
Recurring-Charge Detection).

Every endpoint requires authentication and scopes all data access to
user_id, never a client-supplied identifier -- same discipline as
alerts.py/transactions.py/budgets.py. Subscriptions are only ever created
as a side effect of transaction creation (see the detection call in
transactions.py's create_transaction), so this router only exposes list,
confirm, dismiss, and mark-not-subscription -- no direct POST/create.

Merchant text returned here is plain JSON (via Pydantic serialisation),
never HTML-embedded -- this project has no frontend in-repo, so there is
nothing here that could execute a script payload sitting in `merchant`;
the Gherkin's XSS scenario is about a frontend rendering concern, and the
API's job is simply to never do anything unsafe with the string, which
returning it as a JSON field value already satisfies.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from apps.api.application.commands.confirm_subscription import (
    ConfirmSubscriptionCommand,
    ConfirmSubscriptionHandler,
)
from apps.api.application.commands.dismiss_subscription import (
    DismissSubscriptionCommand,
    DismissSubscriptionHandler,
)
from apps.api.application.commands.mark_not_subscription import (
    MarkNotSubscriptionCommand,
    MarkNotSubscriptionHandler,
)
from apps.api.application.dtos.subscription_dtos import (
    SubscriptionListResponse,
    SubscriptionResponse,
)
from apps.api.application.queries.list_subscriptions import (
    ListSubscriptionsHandler,
    ListSubscriptionsQuery,
)
from apps.api.domain.repositories.subscription_repository import SubscriptionNotFoundError
from apps.api.infrastructure.security.current_user import get_current_user_id
from apps.api.presentation.api.v1.dependencies import (
    get_confirm_subscription_handler,
    get_dismiss_subscription_handler,
    get_list_subscriptions_handler,
    get_mark_not_subscription_handler,
)

logger = logging.getLogger("fintrack.subscriptions")
router = APIRouter(prefix="/api/v1/subscriptions", tags=["subscriptions"])


def _to_response(subscription) -> SubscriptionResponse:
    return SubscriptionResponse(
        id=subscription.id,
        merchant=subscription.merchant,
        amount_estimate=subscription.amount_estimate,
        interval_days=subscription.interval_days,
        occurrences=subscription.occurrences,
        status=subscription.status.value,
        last_transaction_id=subscription.last_transaction_id,
        first_detected_at=subscription.first_detected_at,
        last_seen_at=subscription.last_seen_at,
    )


@router.get("", response_model=SubscriptionListResponse, status_code=status.HTTP_200_OK)
async def list_subscriptions(
    include_dismissed: bool = Query(default=False),
    user_id: uuid.UUID = Depends(get_current_user_id),
    handler: ListSubscriptionsHandler = Depends(get_list_subscriptions_handler),
) -> SubscriptionListResponse:
    subscriptions = await handler.handle(
        ListSubscriptionsQuery(user_id=user_id, include_dismissed=include_dismissed)
    )
    return SubscriptionListResponse(items=[_to_response(s) for s in subscriptions])


@router.post("/{subscription_id}/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_subscription(
    subscription_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    handler: ConfirmSubscriptionHandler = Depends(get_confirm_subscription_handler),
) -> None:
    try:
        await handler.handle(
            ConfirmSubscriptionCommand(subscription_id=subscription_id, user_id=user_id)
        )
    except SubscriptionNotFoundError:
        raise HTTPException(status_code=404, detail="Subscription not found")


@router.post("/{subscription_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_subscription(
    subscription_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    handler: DismissSubscriptionHandler = Depends(get_dismiss_subscription_handler),
) -> None:
    try:
        await handler.handle(
            DismissSubscriptionCommand(subscription_id=subscription_id, user_id=user_id)
        )
    except SubscriptionNotFoundError:
        raise HTTPException(status_code=404, detail="Subscription not found")


@router.post("/{subscription_id}/mark-not-subscription", status_code=status.HTTP_204_NO_CONTENT)
async def mark_not_subscription(
    subscription_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    handler: MarkNotSubscriptionHandler = Depends(get_mark_not_subscription_handler),
) -> None:
    try:
        await handler.handle(
            MarkNotSubscriptionCommand(subscription_id=subscription_id, user_id=user_id)
        )
    except SubscriptionNotFoundError:
        raise HTTPException(status_code=404, detail="Subscription not found")
