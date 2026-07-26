"""Response DTO for the weekly recommendation API. Story: FINTRACK-21.

Read-only endpoint -- no request body, no query parameters at all (unlike
insights.py's trend_months). The only input is the caller's own identity
via the JWT.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class WeeklyRecommendationResponse(BaseModel):
    type: str
    message: str
    category: Optional[str] = None
    merchant: Optional[str] = None
