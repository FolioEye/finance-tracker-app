"""Request/response DTOs for the categorisation-rules API. Pydantic v2
validates external input shape; domain-specific validation (SQLi-shaped
pattern/category rejection) happens in
domain.models.categorisation_rule, same split as transaction_dtos.py.
Story: FINTRACK-17.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CreateCategorisationRuleRequest(BaseModel):
    merchant_pattern: str = Field(..., min_length=1, max_length=255)
    category: str = Field(..., min_length=1, max_length=100)


class CategorisationRuleResponse(BaseModel):
    id: uuid.UUID
    merchant_pattern: str
    category: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
