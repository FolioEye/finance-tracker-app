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


class OAuthLoginRequest(BaseModel):
    """FINTRACK-42/43. `provider` is also implied by the URL path
    (/oauth/google vs /oauth/apple) -- kept in the body too, and checked
    for agreement at the route layer, since which verifier runs is a
    security-relevant decision, not just a routing convenience.
    """

    provider: str = Field(..., pattern="^(google|apple)$")
    id_token: str = Field(..., min_length=1, max_length=4096)

    # NOTE for maintainers: `id_token` must never be passed to a logger,
    # error message, or anywhere else outside this request/handler
    # boundary -- it is a bearer credential for the OAuth provider itself.


class OAuthLoginResponse(BaseModel):
    # Same no-refresh-token-in-body policy as LoginResponse/RegisterResponse.
    user_id: uuid.UUID
    email: str
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    is_new_user: bool

    model_config = {"from_attributes": True}


class RefreshResponse(BaseModel):
    """FINTRACK-60. Response for POST /api/v1/auth/refresh."""

    # Same no-refresh-token-in-body policy as every other response in this
    # module (F-02). The ROTATED refresh token is issued only as the
    # httpOnly cookie -- putting it here too would let an XSS exfiltrate it
    # from the response without ever reading the cookie, which is the exact
    # hole httpOnly exists to close.
    #
    # No `email` field either, deliberately: this endpoint restores a
    # session, and it has no need to handle PII to do that. Pages that
    # display the user's email fetch it from their own authenticated
    # endpoints. See the data-classification table in
    # docs/threat-models/FINTRACK-60-session-persistence-threat-model.md.
    user_id: uuid.UUID
    access_token: str
    token_type: str = "bearer"
    expires_in: int

    model_config = {"from_attributes": True}
