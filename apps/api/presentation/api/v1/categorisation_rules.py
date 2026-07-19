"""Categorisation-rules API endpoint. Story: FINTRACK-17.

Only a create/upsert endpoint exists for this pass -- there's no
Gherkin-tested requirement for listing/deleting rules yet (deferred, see
docs/adr/ADR-012-auto-categorisation-rules-engine.md), matching the same
AC/Gherkin-mismatch-flagging discipline ADR-010/011 used for prior
stories' deferred scope.

Requires authentication and scopes rule creation to that user_id -- same
IDOR-prevention discipline as transactions.py/imports.py.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from apps.api.application.commands.create_categorisation_rule import (
    CreateCategorisationRuleCommand,
    CreateCategorisationRuleHandler,
)
from apps.api.application.dtos.categorisation_rule_dtos import (
    CategorisationRuleResponse,
    CreateCategorisationRuleRequest,
)
from apps.api.domain.models.categorisation_rule import SuspiciousInputError
from apps.api.infrastructure.security.current_user import get_current_user_id
from apps.api.presentation.api.v1.dependencies import get_create_categorisation_rule_handler

logger = logging.getLogger("fintrack.categorisation_rules")
router = APIRouter(prefix="/api/v1/categorisation-rules", tags=["categorisation-rules"])


@router.post("", response_model=CategorisationRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_categorisation_rule(
    payload: CreateCategorisationRuleRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    handler: CreateCategorisationRuleHandler = Depends(get_create_categorisation_rule_handler),
) -> CategorisationRuleResponse:
    try:
        rule = await handler.handle(
            CreateCategorisationRuleCommand(
                user_id=user_id,
                merchant_pattern=payload.merchant_pattern,
                category=payload.category,
            )
        )
    except SuspiciousInputError as exc:
        logger.warning(
            "categorisation_rule_suspicious_input_rejected",
            extra={"context": {"user_id": str(user_id)}},
        )
        raise HTTPException(status_code=400, detail=str(exc))

    logger.info(
        "categorisation_rule_created",
        extra={"context": {"user_id": str(user_id), "rule_id": str(rule.id)}},
    )
    return CategorisationRuleResponse(
        id=rule.id,
        merchant_pattern=rule.merchant_pattern,
        category=rule.category,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )
