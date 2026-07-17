"""StageImportCommand + handler -- AC1/AC2/AC3: parses an uploaded CSV
and stores it as a StagedImport for review. Story: FINTRACK-16.

FINTRACK-17 extends this handler (not parse_csv_statement itself, which
stays a pure parsing function per ADR-011's precedent) with an
auto-categorisation pass: after parsing, the user's CategorisationRule
set is fetched and applied to every row's description before staging, so
the review screen already reflects AC1/AC2/AC5 by the time the user sees
it.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from apps.api.domain.models.import_batch import (
    StagedImport,
    apply_auto_categorisation,
    parse_csv_statement,
)
from apps.api.domain.repositories.categorisation_rule_repository import (
    CategorisationRuleRepository,
)
from apps.api.domain.repositories.import_staging_repository import ImportStagingRepository


@dataclass(frozen=True)
class StageImportCommand:
    user_id: uuid.UUID
    file_bytes: bytes


class StageImportHandler:
    def __init__(
        self,
        staging_repository: ImportStagingRepository,
        categorisation_rule_repository: CategorisationRuleRepository,
    ) -> None:
        self._staging = staging_repository
        self._categorisation_rules = categorisation_rule_repository

    async def handle(self, command: StageImportCommand) -> StagedImport:
        # Raises CorruptedFileError -- mapped to 400 at the API layer
        # (AC6: clear error, not a silent partial import).
        rows = parse_csv_statement(command.file_bytes)

        # FINTRACK-17: pattern-match each row's description against this
        # user's rules (AC1), forcing "Uncategorised" where nothing
        # matches (AC2) -- see apply_auto_categorisation's docstring for
        # why this supersedes the CSV's own category column.
        rules = await self._categorisation_rules.list_for_user(command.user_id)
        apply_auto_categorisation(rows, rules)

        staged_import = StagedImport(
            id=uuid.uuid4(),
            user_id=command.user_id,
            rows=rows,
        )
        await self._staging.save(staged_import)
        return staged_import
