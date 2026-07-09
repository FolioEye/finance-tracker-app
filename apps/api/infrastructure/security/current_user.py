"""Bearer-token authentication dependency. New for FINTRACK-15 -- the first
story with an authenticated business-data endpoint (register/login/logout
issue tokens but don't themselves require one).

Trusts the JWT's `sub` claim directly after signature+expiry verification,
rather than re-querying the users table on every request -- stateless per
12-factor, and the same "access token window" trade-off ADR-009 already
accepted for logout (a deactivated account's already-issued access token
stays valid for its own <=15-minute remaining lifetime; full revocation
would require a DB or Redis lookup on every single authenticated request,
which the constraint matrix's performance goals don't justify for this
story's scope).
"""
from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from apps.api.config import Settings, get_settings
from apps.api.infrastructure.security.token_service import (
    ExpiredTokenError,
    InvalidTokenError,
    TokenService,
)

# tokenUrl is only used to populate OpenAPI's "Authorize" UI -- this
# project's actual login flow is POST /api/v1/auth/login with a JSON body,
# not the OAuth2 password-grant form this class was originally designed
# for. auto_error=False so a missing header raises our own 401 with a
# message consistent with the rest of this API, rather than FastAPI's
# default "Not authenticated".
_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


async def get_current_user_id(
    token: str | None = Depends(_oauth2_scheme),
    settings: Settings = Depends(get_settings),
) -> uuid.UUID:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not token:
        raise credentials_error

    tokens = TokenService(
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        access_token_expire_minutes=settings.access_token_expire_minutes,
        refresh_token_expire_days=settings.refresh_token_expire_days,
    )

    try:
        claims = tokens.decode(token)
    except (ExpiredTokenError, InvalidTokenError):
        raise credentials_error

    if claims.get("type") != "access":
        # A refresh token (or any other type) presented as a bearer token
        # is not a valid access credential -- same principle as
        # logout_user.py rejecting an access token used as a refresh token.
        raise credentials_error

    sub = claims.get("sub")
    if not sub:
        raise credentials_error

    try:
        return uuid.UUID(sub)
    except ValueError:
        raise credentials_error
