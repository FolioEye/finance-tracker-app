"""Request/response DTOs for the auth API. Pydantic v2 validates all external input."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    # Deliberately a plain str, not Pydantic's EmailStr. EmailStr would
    # validate format at this layer, before the request ever reaches the
    # handler -- short-circuiting apps.api.domain.models.user.Email's own
    # validation with a generic 422 that doesn't match the documented AC
    # ("Invalid email format", 400) and echoes the raw input back in its
    # error message. A max_length bound is kept here as a basic payload-size
    # guard; real format/SQLi/XSS-shaped rejection happens in the domain
    # layer, per FINTRACK-13's Gherkin. Found during QA Lead review.
    email: str = Field(..., min_length=1, max_length=320)
    password: str = Field(..., min_length=1, max_length=128)
    confirm_password: str = Field(..., min_length=1, max_length=128)

    # NOTE for maintainers: `password` and `confirm_password` must never be
    # passed to a logger, error message, or anywhere else outside this
    # request/handler boundary. See constraint matrix.


class RegisterResponse(BaseModel):
    # refresh_token is deliberately NOT included here (F-02, fixed 2026-07-06).
    # It is issued only as an httpOnly/Secure/SameSite=Strict cookie (see
    # apps/api/presentation/api/v1/auth.py) -- returning it in the JSON body
    # too meant an XSS could exfiltrate it from the response even without
    # reading the cookie directly, partially defeating httpOnly's purpose.
    # Flagged at Tech Lead/QA Lead/Release Pro stages and by three
    # consecutive audit runs before being fixed.
    user_id: uuid.UUID
    email: str
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    email_verification_pending: bool = True

    model_config = {"from_attributes": True}


class LoginRequest(BaseModel):
    # Same rationale as RegisterRequest: plain str, not EmailStr -- format
    # validation happens in the domain layer so malformed/SQLi-shaped input
    # gets the same generic invalid-credentials handling as any other
    # login failure, rather than a distinguishable 422 from Pydantic.
    email: str = Field(..., min_length=1, max_length=320)
    password: str = Field(..., min_length=1, max_length=128)

    # NOTE for maintainers: `password` must never be passed to a logger,
    # error message, or anywhere else outside this request/handler boundary.


class LoginResponse(BaseModel):
    # No refresh_token in the body -- same F-02 rationale as RegisterResponse.
    # Issued only as an httpOnly/Secure/SameSite=Strict cookie.
    user_id: uuid.UUID
    email: str
    access_token: str
    token_type: str = "bearer"
    expires_in: int

    model_config = {"from_attributes": True}


class LogoutResponse(BaseModel):
    detail: str = "Logged out successfully"
