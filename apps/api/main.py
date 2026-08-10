"""FastAPI application entrypoint."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from apps.api.config import get_settings
from apps.api.presentation.api.v1.alerts import router as alerts_router
from apps.api.presentation.api.v1.auth import limiter
from apps.api.presentation.api.v1.auth import router as auth_router
from apps.api.presentation.api.v1.budgets import router as budgets_router
from apps.api.presentation.api.v1.categorisation_rules import router as categorisation_rules_router
from apps.api.presentation.api.v1.follow_through import router as follow_through_router
from apps.api.presentation.api.v1.imports import router as imports_router
from apps.api.presentation.api.v1.insights import router as insights_router
from apps.api.presentation.api.v1.recommendations import router as recommendations_router
from apps.api.presentation.api.v1.subscriptions import router as subscriptions_router
from apps.api.presentation.api.v1.transactions import router as transactions_router

logging.basicConfig(
    level=logging.INFO,
    format=(
        '{"timestamp": "%(asctime)s", "level": "%(levelname)s", '
        '"service": "fintrack-api", "message": "%(message)s"}'
    ),
)

settings = get_settings()

app = FastAPI(title=settings.app_name, debug=settings.debug)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS -- see config.py's cors_allowed_origins docstring for the incident
# this closes (FINTRACK-38, 2026-08-09: middleware was entirely absent,
# so every browser call from apps/web, including OAuth login, was always
# going to be blocked regardless of frontend domain). Only registered
# when at least one origin is configured -- an empty allow_origins list
# on CORSMiddleware would still add CORS headers with no origins ever
# matching, which is a more confusing failure mode than just not adding
# the middleware at all when nothing's configured (e.g. local dev).
_cors_origins = [origin.strip() for origin in settings.cors_allowed_origins.split(",") if origin.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
elif settings.environment == "production":
    # Not a hard crash -- health endpoints and non-browser callers (e.g.
    # server-to-server) still need to work -- but this must be loud
    # somewhere, since a silently-empty value here means the frontend
    # simply can't log anyone in and looks like a frontend bug instead.
    logging.getLogger("fintrack.api").warning(
        "cors_not_configured",
        extra={
            "context": {
                "reason": "CORS_ALLOWED_ORIGINS is unset in production -- "
                "browser requests from apps/web will be blocked by CORS",
            }
        },
    )

app.include_router(auth_router)
app.include_router(transactions_router)
app.include_router(imports_router)
app.include_router(categorisation_rules_router)
app.include_router(budgets_router)
app.include_router(alerts_router)
app.include_router(subscriptions_router)
app.include_router(insights_router)
app.include_router(recommendations_router)
app.include_router(follow_through_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/health/ready")
async def health_ready() -> dict:
    # Liveness vs readiness kept separate; readiness will check DB/Redis
    # connectivity once those checks are needed beyond this first story.
    return {"status": "ready"}


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logging.getLogger("fintrack.api").error(
        "unhandled_exception", extra={"context": {"path": str(request.url.path)}}
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
