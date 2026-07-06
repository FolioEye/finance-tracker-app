"""Auth API endpoints. Story: FINTRACK-13 (User Registration).

Note: deliberately NOT using `from __future__ import annotations` here.
Combined with this project's pinned fastapi==0.115.0 + pydantic==2.9.2,
postponed evaluation of annotations breaks FastAPI's route registration
at import time (PydanticUndefinedAnnotation on RegisterRequest) -- found
during QA Lead's integration testing, since the original unit/security
tests only exercised the handler class directly and never actually
imported the live app. Verified live: removing this import is sufficient
for the app to import and all routes to register correctly.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from slowapi import Limiter
from slowapi.util import get_remote_address

from apps.api.application.commands.register_user import (
    PasswordMismatchError,
    RegisterUserCommand,
    RegisterUserHandler,
)
from apps.api.application.dtos.auth_dtos import RegisterRequest, RegisterResponse
from apps.api.config import get_settings
from apps.api.domain.models.user import InvalidEmailError, WeakPasswordError
from apps.api.domain.repositories.user_repository import EmailAlreadyExistsError
from apps.api.presentation.api.v1.dependencies import get_register_user_handler

logger = logging.getLogger("fintrack.auth")
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_settings = get_settings()
limiter = Limiter(key_func=get_remote_address)


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(
    f"{_settings.register_rate_limit_attempts}/{_settings.register_rate_limit_window_minutes}minute"
)
async def register(
    request: Request,
    payload: RegisterRequest,
    response: Response,
    handler: RegisterUserHandler = Depends(get_register_user_handler),
) -> RegisterResponse:
    # Structured log -- deliberately NO password field. Only a non-identifying
    # email domain is logged, never the full address or the password.
    logger.info(
        "registration_attempt",
        extra={"context": {"email_domain": payload.email.split("@")[-1]}},
    )

    command = RegisterUserCommand(
        email=payload.email,
        password=payload.password,
        confirm_password=payload.confirm_password,
    )

    try:
        result = await handler.handle(command)
    except PasswordMismatchError:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    except InvalidEmailError:
        raise HTTPException(status_code=400, detail="Invalid email format")
    except WeakPasswordError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except EmailAlreadyExistsError:
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    # Refresh token as httpOnly Secure cookie, SameSite=Strict per constraint matrix.
    response.set_cookie(
        key="refresh_token",
        value=result.tokens.refresh_token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=_settings.refresh_token_expire_days * 24 * 60 * 60,
        path="/api/v1/auth",
    )

    logger.info("registration_succeeded", extra={"context": {"user_id": str(result.user.id)}})

    return RegisterResponse(
        user_id=result.user.id,
        email=str(result.user.email),
        access_token=result.tokens.access_token,
        expires_in=result.tokens.access_token_expires_in_seconds,
        email_verification_pending=True,
    )
