"""Budgets API endpoints. Story: FINTRACK-20 (Simple Budget Tracking).

Every endpoint requires authentication (get_current_user_id) and scopes
all data access to that user_id -- never a client-supplied identifier,
same IDOR-prevention discipline as transactions.py/categorisation_rules.py.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from apps.api.application.commands.create_budget import (
    CreateBudgetCommand,
    CreateBudgetHandler,
)
from apps.api.application.commands.delete_budget import (
    DeleteBudgetCommand,
    DeleteBudgetHandler,
)
from apps.api.application.commands.update_budget import (
    UpdateBudgetCommand,
    UpdateBudgetHandler,
)
from apps.api.application.dtos.budget_dtos import (
    BudgetOverviewItemResponse,
    BudgetOverviewResponse,
    BudgetResponse,
    CreateBudgetRequest,
    UpdateBudgetRequest,
)
from apps.api.application.queries.get_budget_overview import (
    BudgetOverviewItem,
    GetBudgetOverviewHandler,
    GetBudgetOverviewQuery,
)
from apps.api.domain.models.budget import InvalidBudgetAmountError
from apps.api.domain.models.transaction import SuspiciousInputError
from apps.api.domain.repositories.budget_repository import (
    BudgetAlreadyExistsError,
    BudgetNotFoundError,
)
from apps.api.infrastructure.security.current_user import get_current_user_id
from apps.api.presentation.api.v1.dependencies import (
    get_create_budget_handler,
    get_delete_budget_handler,
    get_get_budget_overview_handler,
    get_update_budget_handler,
)

logger = logging.getLogger("fintrack.budgets")
router = APIRouter(prefix="/api/v1/budgets", tags=["budgets"])


def _to_response(budget) -> BudgetResponse:
    return BudgetResponse(
        id=budget.id,
        category=budget.category,
        monthly_limit=str(budget.monthly_limit),
        created_at=budget.created_at,
        updated_at=budget.updated_at,
    )


def _overview_item_to_response(item: BudgetOverviewItem) -> BudgetOverviewItemResponse:
    return BudgetOverviewItemResponse(
        budget_id=item.budget_id,
        category=item.category,
        monthly_limit=str(item.monthly_limit) if item.monthly_limit is not None else None,
        spent=str(item.spent),
        percent_used=str(item.percent_used) if item.percent_used is not None else None,
        is_over_budget=item.is_over_budget,
    )


@router.post("", response_model=BudgetResponse, status_code=status.HTTP_201_CREATED)
async def create_budget(
    payload: CreateBudgetRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    handler: CreateBudgetHandler = Depends(get_create_budget_handler),
) -> BudgetResponse:
    try:
        budget = await handler.handle(
            CreateBudgetCommand(
                user_id=user_id, category=payload.category, monthly_limit=payload.monthly_limit
            )
        )
    except BudgetAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except InvalidBudgetAmountError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except SuspiciousInputError as exc:
        logger.warning(
            "budget_suspicious_input_rejected", extra={"context": {"user_id": str(user_id)}}
        )
        raise HTTPException(status_code=400, detail=str(exc))

    logger.info(
        "budget_created", extra={"context": {"user_id": str(user_id), "budget_id": str(budget.id)}}
    )
    return _to_response(budget)


@router.get("", response_model=BudgetOverviewResponse, status_code=status.HTTP_200_OK)
async def get_budget_overview(
    user_id: uuid.UUID = Depends(get_current_user_id),
    handler: GetBudgetOverviewHandler = Depends(get_get_budget_overview_handler),
) -> BudgetOverviewResponse:
    items = await handler.handle(GetBudgetOverviewQuery(user_id=user_id))
    return BudgetOverviewResponse(items=[_overview_item_to_response(item) for item in items])


@router.patch("/{budget_id}", response_model=BudgetResponse, status_code=status.HTTP_200_OK)
async def update_budget(
    budget_id: uuid.UUID,
    payload: UpdateBudgetRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    handler: UpdateBudgetHandler = Depends(get_update_budget_handler),
) -> BudgetResponse:
    try:
        budget = await handler.handle(
            UpdateBudgetCommand(
                budget_id=budget_id, user_id=user_id, monthly_limit=payload.monthly_limit
            )
        )
    except BudgetNotFoundError:
        raise HTTPException(status_code=404, detail="Budget not found")
    except InvalidBudgetAmountError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    logger.info(
        "budget_updated", extra={"context": {"user_id": str(user_id), "budget_id": str(budget_id)}}
    )
    return _to_response(budget)


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_budget(
    budget_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    handler: DeleteBudgetHandler = Depends(get_delete_budget_handler),
) -> None:
    try:
        await handler.handle(DeleteBudgetCommand(budget_id=budget_id, user_id=user_id))
    except BudgetNotFoundError:
        raise HTTPException(status_code=404, detail="Budget not found")

    logger.info(
        "budget_deleted", extra={"context": {"user_id": str(user_id), "budget_id": str(budget_id)}}
    )
