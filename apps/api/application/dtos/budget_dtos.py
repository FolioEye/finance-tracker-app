"""Request/response DTOs for the budgets API. Pydantic v2 validates
external input shape; domain-specific validation (positive-amount check,
SQLi-shaped-text rejection) happens in domain.models.budget, same split
as transaction_dtos.py and categorisation_rule_dtos.py. Story: FINTRACK-20.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class CreateBudgetRequest(BaseModel):
    category: str = Field(..., min_length=1, max_length=100)
    monthly_limit: str = Field(..., min_length=1, max_length=20)


class UpdateBudgetRequest(BaseModel):
    monthly_limit: str = Field(..., min_length=1, max_length=20)


class BudgetResponse(BaseModel):
    id: uuid.UUID
    category: str
    monthly_limit: str
    created_at: datetime
    updated_at: datetime


class BudgetOverviewItemResponse(BaseModel):
    """budget_id/monthly_limit/percent_used are all nullable together --
    a null monthly_limit means this category has no budget (AC5), and the
    frontend should render spend-only, with no progress bar or over/under
    indicator at all, rather than defaulting to some numeric placeholder.
    """

    budget_id: uuid.UUID | None
    category: str
    monthly_limit: str | None
    spent: str
    percent_used: str | None
    is_over_budget: bool


class BudgetOverviewResponse(BaseModel):
    items: list[BudgetOverviewItemResponse]


def _decimal_to_str(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None
