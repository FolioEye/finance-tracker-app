"""FastAPI application entrypoint."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from apps.api.config import get_settings
from apps.api.presentation.api.v1.auth import limiter
from apps.api.presentation.api.v1.auth import router as auth_router
from apps.api.presentation.api.v1.budgets import router as budgets_router
from apps.api.presentation.api.v1.categorisation_rules import router as categorisation_rules_router
from apps.api.presentation.api.v1.imports import router as imports_router
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

app.include_router(auth_router)
app.include_router(transactions_router)
app.include_router(imports_router)
app.include_router(categorisation_rules_router)
app.include_router(budgets_router)


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
