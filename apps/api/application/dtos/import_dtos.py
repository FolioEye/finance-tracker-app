"""Request/response DTOs for the imports API. Pydantic v2 validates
external input shape; domain-specific validation (date/amount parsing,
formula-injection sanitisation) happens in domain.models.import_batch,
same split as transaction_dtos.py. Story: FINTRACK-16.
"""
from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class StagedRowResponse(BaseModel):
    row_index: int
    raw_date: str
    raw_amount: str
    category: str
    note: str | None
    status: str
    warning: str | None
    # FINTRACK-17 AC6: which CategorisationRule produced `category`, so
    # the review screen can show "which rule produced the match" (null
    # when no rule matched and category is the "Uncategorised" default).
    matched_rule_id: uuid.UUID | None = None


class StageImportResponse(BaseModel):
    import_id: uuid.UUID
    found_count: int
    flagged_count: int
    invalid_count: int
    # FINTRACK-17 AC5: "X of Y auto-categorised, Z need review" summary.
    auto_categorised_count: int
    needs_review_count: int
    rows: list[StagedRowResponse]


class RowEditRequest(BaseModel):
    row_index: int
    raw_date: str | None = None
    raw_amount: str | None = Field(default=None, max_length=20)
    category: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=500)


class UpdateStagedRowsRequest(BaseModel):
    edits: list[RowEditRequest]


class CommitImportResponse(BaseModel):
    committed_count: int
    skipped_count: int
