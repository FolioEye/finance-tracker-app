"""StageImportCommand + handler -- AC1/AC2/AC3: parses an uploaded CSV
and stores it as a StagedImport for review. Story: FINTRACK-16.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from apps.api.domain.models.import_batch import StagedImport, parse_csv_statement
from apps.api.domain.repositories.import_staging_repository import ImportStagingRepository


@dataclass(frozen=True)
class StageImportCommand:
    user_id: uuid.UUID
    file_bytes: bytes


class StageImportHandler:
    def __init__(self, staging_repository: ImportStagingRepository) -> None:
        self._staging = staging_repository

    async def handle(self, command: StageImportCommand) -> StagedImport:
        # Raises CorruptedFileError -- mapped to 400 at the API layer
        # (AC6: clear error, not a silent partial import).
        rows = parse_csv_statement(command.file_bytes)

        staged_import = StagedImport(
            id=uuid.uuid4(),
            user_id=command.user_id,
            rows=rows,
        )
        await self._staging.save(staged_import)
        return staged_import
