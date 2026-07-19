"""Transactions API endpoints. Story: FINTRACK-15 (Add Manual Transaction).

Every endpoint requires authentication (get_current_user_id) and scopes
all data access to that user_id -- never a client-supplied identifier.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from apps.api.application.commands.create_transaction import (
    CreateTransactionCommand,
    CreateTransactionHandler,
)
from apps.api.application.commands.delete_transaction import (
    DeleteTransactionCommand,
    DeleteTransactionHandler,
)
from apps.api.application.commands.evaluate_alerts_for_transaction import (
    EvaluateAlertsForTransactionCommand,
    EvaluateAlertsForTransactionHandler,
)
from apps.api.application.commands.update_transaction import (
    UpdateTransactionCommand,
    UpdateTransactionHandler,
)
from apps.api.application.dtos.transaction_dtos import (
    CreateTransactionRequest,
    TransactionListResponse,
    TransactionResponse,
    UpdateTransactionRequest,
)
from apps.api.application.queries.list_transactions import (
    ListTransactionsHandler,
    ListTransactionsQuery,
)
from apps.api.domain.models.transaction import (
    AmountExceedsMaximumError,
    InvalidAmountError,
    SuspiciousInputError,
)
from apps.api.domain.repositories.transaction_repository import TransactionNotFoundError
from apps.api.infrastructure.security.current_user import get_current_user_id
from apps.api.presentation.api.v1.dependencies import (
    get_create_transaction_handler,
    get_delete_transaction_handler,
    get_evaluate_alerts_for_transaction_handler,
    get_list_transactions_handler,
    get_update_transaction_handler,
)

logger = logging.getLogger("fintrack.transactions")
router = APIRouter(prefix="/api/v1/transactions", tags=["transactions"])


def _to_response(transaction) -> TransactionResponse:
    return TransactionResponse(
        id=transaction.id,
        amount=str(transaction.amount),
        category=transaction.category,
        transaction_date=transaction.transaction_date,
        note=transaction.note,
        entry_source=transaction.entry_source,
    )


@router.post("", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    payload: CreateTransactionRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    handler: CreateTransactionHandler = Depends(get_create_transaction_handler),
    alert_handler: EvaluateAlertsForTransactionHandler = Depends(
        get_evaluate_alerts_for_transaction_handler
    ),
) -> TransactionResponse:
    command = CreateTransactionCommand(
        user_id=user_id,
        amount=payload.amount,
        category=payload.category,
        transaction_date=payload.transaction_date,
        note=payload.note,
    )

    try:
        transaction = await handler.handle(command)
    except AmountExceedsMaximumError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except InvalidAmountError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except SuspiciousInputError as exc:
        logger.warning(
            "transaction_suspicious_input_rejected",
            extra={"context": {"user_id": str(user_id)}},
        )
        raise HTTPException(status_code=400, detail=str(exc))

    logger.info(
        "transaction_created", extra={"context": {"user_id": str(user_id), "transaction_id": str(transaction.id)}}
    )

    # FINTRACK-22: best-effort alert evaluation. Composed here at the
    # presentation layer -- deliberately not inside CreateTransactionHandler
    # -- so a bug in threshold/large-transaction logic can never turn a
    # successful transaction write into a failed request. See
    # docs/adr/ADR-014-threshold-alerts-write-time-detection.md.
    try:
        await alert_handler.handle(
            EvaluateAlertsForTransactionCommand(
                user_id=user_id,
                transaction_id=transaction.id,
                category=transaction.category,
                amount=transaction.amount.value,
                transaction_date=transaction.transaction_date,
            )
        )
    except Exception:  # noqa: BLE001 -- deliberate catch-all, see comment above
        logger.error(
            "alert_evaluation_failed",
            extra={"context": {"user_id": str(user_id), "transaction_id": str(transaction.id)}},
        )

    return _to_response(transaction)


@router.get("", response_model=TransactionListResponse, status_code=status.HTTP_200_OK)
async def list_transactions(
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    user_id: uuid.UUID = Depends(get_current_user_id),
    handler: ListTransactionsHandler = Depends(get_list_transactions_handler),
) -> TransactionListResponse:
    page = await handler.handle(ListTransactionsQuery(user_id=user_id, limit=limit, cursor=cursor))
    return TransactionListResponse(
        items=[_to_response(t) for t in page.items],
        next_cursor=page.next_cursor,
    )


@router.patch("/{transaction_id}", response_model=TransactionResponse, status_code=status.HTTP_200_OK)
async def update_transaction(
    transaction_id: uuid.UUID,
    payload: UpdateTransactionRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    handler: UpdateTransactionHandler = Depends(get_update_transaction_handler),
) -> TransactionResponse:
    command = UpdateTransactionCommand(
        transaction_id=transaction_id,
        user_id=user_id,
        amount=payload.amount,
        category=payload.category,
        transaction_date=payload.transaction_date,
        note=payload.note,
    )

    try:
        transaction = await handler.handle(command)
    except TransactionNotFoundError:
        raise HTTPException(status_code=404, detail="Transaction not found")
    except AmountExceedsMaximumError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except InvalidAmountError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except SuspiciousInputError as exc:
        logger.warning(
            "transaction_suspicious_input_rejected",
            extra={"context": {"user_id": str(user_id), "transaction_id": str(transaction_id)}},
        )
        raise HTTPException(status_code=400, detail=str(exc))

    return _to_response(transaction)


@router.delete("/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transaction(
    transaction_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    handler: DeleteTransactionHandler = Depends(get_delete_transaction_handler),
) -> None:
    try:
        await handler.handle(DeleteTransactionCommand(transaction_id=transaction_id, user_id=user_id))
    except TransactionNotFoundError:
        raise HTTPException(status_code=404, detail="Transaction not found")
