"""Statement/CSV import API endpoints. Story: FINTRACK-16.

Two-phase flow: POST stages a parsed-but-unconfirmed import for review
(AC1/AC2/AC3), PATCH lets the user bulk-edit flagged/invalid rows before
committing (AC4), POST .../commit replays the committable rows through
the same transaction-creation path manual entry uses (AC5, entry_source=
csv_import), DELETE lets the user discard a staged import without
committing anything.

Every endpoint requires authentication and scopes staged-import access to
that user_id -- same IDOR-prevention discipline as transactions.py.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status

from apps.api.application.commands.commit_import import (
    CommitImportCommand,
    CommitImportHandler,
    NothingToCommitError,
)
from apps.api.application.commands.stage_import import StageImportCommand, StageImportHandler
from apps.api.application.commands.update_staged_rows import (
    RowEdit,
    UpdateStagedRowsCommand,
    UpdateStagedRowsHandler,
)
from apps.api.application.dtos.import_dtos import (
    CommitImportResponse,
    StagedRowResponse,
    StageImportResponse,
    UpdateStagedRowsRequest,
)
from apps.api.domain.models.import_batch import CorruptedFileError, StagedImport
from apps.api.domain.repositories.import_staging_repository import (
    ImportStagingRepository,
    StagedImportNotFoundError,
)
from apps.api.infrastructure.security.current_user import get_current_user_id
from apps.api.presentation.api.v1.dependencies import (
    get_commit_import_handler,
    get_import_staging_repository,
    get_stage_import_handler,
    get_update_staged_rows_handler,
)

logger = logging.getLogger("fintrack.imports")
router = APIRouter(prefix="/api/v1/imports", tags=["imports"])

# AC1 scope note: CSV only for this pass -- PDF/XLSX are not implemented
# (no Gherkin scenario exercises them); see docs/adr/ADR-011.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB


def _to_response(staged_import: StagedImport) -> StageImportResponse:
    return StageImportResponse(
        import_id=staged_import.id,
        found_count=staged_import.found_count,
        flagged_count=staged_import.flagged_count,
        invalid_count=staged_import.invalid_count,
        rows=[
            StagedRowResponse(
                row_index=r.row_index,
                raw_date=r.raw_date,
                raw_amount=r.raw_amount,
                category=r.category,
                note=r.note,
                status=r.status.value,
                warning=r.warning,
            )
            for r in staged_import.rows
        ],
    )


@router.post("", response_model=StageImportResponse, status_code=status.HTTP_201_CREATED)
async def stage_import(
    file: UploadFile,
    user_id: uuid.UUID = Depends(get_current_user_id),
    handler: StageImportHandler = Depends(get_stage_import_handler),
) -> StageImportResponse:
    file_bytes = await file.read()
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="File exceeds maximum upload size (5 MB)")

    try:
        staged_import = await handler.handle(
            StageImportCommand(user_id=user_id, file_bytes=file_bytes)
        )
    except CorruptedFileError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if staged_import.flagged_count:
        logger.warning(
            "import_suspicious_content_sanitised",
            extra={
                "context": {
                    "user_id": str(user_id),
                    "import_id": str(staged_import.id),
                    "flagged_count": staged_import.flagged_count,
                }
            },
        )
    logger.info(
        "import_staged",
        extra={
            "context": {
                "user_id": str(user_id),
                "import_id": str(staged_import.id),
                "found_count": staged_import.found_count,
                "flagged_count": staged_import.flagged_count,
                "invalid_count": staged_import.invalid_count,
            }
        },
    )
    return _to_response(staged_import)


@router.patch("/{import_id}", response_model=StageImportResponse, status_code=status.HTTP_200_OK)
async def update_staged_rows(
    import_id: uuid.UUID,
    payload: UpdateStagedRowsRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    handler: UpdateStagedRowsHandler = Depends(get_update_staged_rows_handler),
) -> StageImportResponse:
    edits = [
        RowEdit(
            row_index=e.row_index,
            raw_date=e.raw_date,
            raw_amount=e.raw_amount,
            category=e.category,
            note=e.note,
        )
        for e in payload.edits
    ]
    try:
        staged_import = await handler.handle(
            UpdateStagedRowsCommand(user_id=user_id, import_id=import_id, edits=edits)
        )
    except StagedImportNotFoundError:
        raise HTTPException(status_code=404, detail="Staged import not found")

    return _to_response(staged_import)


@router.post(
    "/{import_id}/commit", response_model=CommitImportResponse, status_code=status.HTTP_200_OK
)
async def commit_import(
    import_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    handler: CommitImportHandler = Depends(get_commit_import_handler),
) -> CommitImportResponse:
    try:
        result = await handler.handle(CommitImportCommand(user_id=user_id, import_id=import_id))
    except StagedImportNotFoundError:
        raise HTTPException(status_code=404, detail="Staged import not found")
    except NothingToCommitError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    logger.info(
        "import_committed",
        extra={
            "context": {
                "user_id": str(user_id),
                "import_id": str(import_id),
                "committed_count": result.committed_count,
                "skipped_count": result.skipped_count,
            }
        },
    )
    return CommitImportResponse(
        committed_count=result.committed_count, skipped_count=result.skipped_count
    )


@router.delete("/{import_id}", status_code=status.HTTP_204_NO_CONTENT)
async def discard_import(
    import_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    staging: ImportStagingRepository = Depends(get_import_staging_repository),
) -> None:
    await staging.delete(import_id, user_id)
