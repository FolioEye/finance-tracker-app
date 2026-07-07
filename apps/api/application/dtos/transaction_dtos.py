"""Request/response DTOs for the transactions API. Pydantic v2 validates
external input shape; domain-specific validation (amount range/precision,
SQLi-shaped-text rejection) happens in domain.models.transaction, same
split as auth_dtos.py.
"""
from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field


class CreateTransactionRequest(BaseModel):
    amount: str = Field(..., min_length=1, max_length=20)
    category: str = Field(..., min_length=1, max_length=100)
    transaction_date: date
    note: str | None = Field(default=None, max_length=500)


class UpdateTransactionRequest(BaseModel):
    amount: str | None = Field(default=None, min_length=1, max_length=20)
    category: str | None = Field(default=None, min_length=1, max_length=100)
    transaction_date: date | None = None
    note: str | None = Field(default=None, max_length=500)


class TransactionResponse(BaseModel):
    id: uuid.UUID
    amount: str
    category: str
    transaction_date: date
    note: str | None

    model_config = {"from_attributes": True}


class TransactionListResponse(BaseModel):
    items: list[TransactionResponse]
    next_cursor: str | None
