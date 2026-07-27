"""Response DTO for the weekly recommendation API. Story: FINTRACK-21,
extended by FINTRACK-23.

Read-only endpoint -- no request body, no query parameters at all (unlike
insights.py's trend_months). The only input is the caller's own identity
via the JWT.

follow_through_record_id (FINTRACK-23): the id of the FollowThroughRecord
the presentation layer ensured exists for today (see recommendations.py),
so the client has something stable to POST an action against at
/api/v1/follow-through/{id}/actions. This is intentionally the only
FINTRACK-23 concept exposed on this response -- FINTRACK-21's own handler
and payload are otherwise completely unmodified by this story.
"""
from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel


class WeeklyRecommendationResponse(BaseModel):
    type: str
    message: str
    category: Optional[str] = None
    merchant: Optional[str] = None
    follow_through_record_id: Optional[uuid.UUID] = None
