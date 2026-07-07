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

from apps.api.application.commands.login_user import InvalidCredentialsError, LoginUserCommand, LoginUserHandler
from apps.api.application.commands.logout_user import (
    LogoutUserCommand,
    LogoutUserHandler,
    NoActiveSessionError,
)
from apps.api.application.commands.register_user import (
    PasswordMismatchError,
    RegisterUserCommand,
    RegisterUserHandler,
)
from apps.api.application.dtos.auth_dtos import (
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    RegisterRequest,
    RegisterResponse,
)
from apps.api.config import get_settings
from apps.api.domain.models.user import InvalidEmailError, WeakPasswordError
from apps.api.domain.repositories.user_repository import EmailAlreadyExistsError
from apps.api.infrastructure.security.rate_limiter import RateLimitExceededError
from apps.api.presentation.api.v1.dependencies import (
    get_login_user_handler,
    get_logout_user_handler,
    get_register_user_handler,
)

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


@router.post("/login", response_model=LoginResponse, status_code=status.HTTP_200_OK)
async def login(
    request: Request,
    payload: LoginRequest,
    response: Response,
    handler: LoginUserHandler = Depends(get_login_user_handler),
) -> LoginResponse:
    # Same domain-only logging discipline as /register: no password, no
    # full email, only the domain portion for basic observability.
    logger.info(
        "login_attempt",
        extra={
            "context": {
                "email_domain": payload.email.split("@")[-1] if "@" in payload.email else "n/a"
            }
        },
    )

    command = LoginUserCommand(
        email=payload.email,
        password=payload.password,
        client_ip=get_remote_address(request),
    )

    try:
        result = await handler.handle(command)
    except RateLimitExceededError:
        logger.warning("login_rate_limited", extra={"context": {}})
        raise HTTPException(status_code=429, detail="Too many attempts, try again later")
    except InvalidCredentialsError:
        # Deliberately the same log event and HTTP response regardless of
        # *why* the credentials were rejected (unknown email, malformed/
        # SQLi-shaped email, deactivated account, or wrong password) --
        # see LoginUserHandler for the no-user-enumeration rationale.
        logger.info("login_failed", extra={"context": {}})
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Refresh token as httpOnly Secure cookie, SameSite=Strict -- same
    # shape as /register's cookie.
    response.set_cookie(
        key="refresh_token",
        value=result.tokens.refresh_token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=_settings.refresh_token_expire_days * 24 * 60 * 60,
        path="/api/v1/auth",
    )

    logger.info("login_succeeded", extra={"context": {"user_id": str(result.user.id)}})

    return LoginResponse(
        user_id=result.user.id,
        email=str(result.user.email),
        access_token=result.tokens.access_token,
        expires_in=result.tokens.access_token_expires_in_seconds,
    )


@router.post("/logout", response_model=LogoutResponse, status_code=status.HTTP_200_OK)
async def logout(
    request: Request,
    response: Response,
    handler: LogoutUserHandler = Depends(get_logout_user_handler),
) -> LogoutResponse:
    refresh_token = request.cookies.get("refresh_token", "")

    try:
        await handler.handle(LogoutUserCommand(refresh_token=refresh_token))
    except NoActiveSessionError:
        # Logout is safe to call with no session -- clear any stray cookie
        # and report success either way, since the end state (no valid
        # session) is identical.
        pass

    # Explicitly match set_cookie's attributes (httponly/secure/samesite) --
    # without repeating them here, delete_cookie() falls back to
    # Starlette's own defaults (samesite="lax") instead of this project's
    # SameSite=Strict policy. Found via a live production smoke test
    # (2026-07-07): functionally harmless since browsers match a cookie
    # for deletion by name+domain+path, not by attributes, so the cookie
    # was still cleared correctly either way -- but leaving it implicit
    # meant this endpoint silently depended on a framework default rather
    # than this project's own stated cookie policy.
    response.delete_cookie(
        key="refresh_token",
        path="/api/v1/auth",
        httponly=True,
        secure=True,
        samesite="strict",
    )
    logger.info("logout_succeeded", extra={"context": {}})
    return LogoutResponse()
