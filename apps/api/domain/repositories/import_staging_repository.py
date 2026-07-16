"""Port (interface) for staged-import persistence. Infrastructure provides
the Redis adapter. Story: FINTRACK-16.

Deliberately not the transactions table -- a StagedImport is transient
review-state, not committed financial data, matching the existing
pattern this codebase already uses for other short-lived server-side
state (rate-limit counters, revoked-token denylist entries).
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod

from apps.api.domain.models.import_batch import StagedImport


class StagedImportNotFoundError(Exception):
    """Raised when a staged import doesn't exist -- either it was never
    created, already committed/discarded, or its 30-minute TTL expired.
    Also raised (deliberately, not distinguished) when it exists but
    belongs to a different user_id, per this project's IDOR-prevention
    discipline (see TransactionNotFoundError for the same pattern)."""


class ImportStagingRepository(ABC):
    @abstractmethod
    async def save(self, staged_import: StagedImport) -> None:
        ...

    @abstractmethod
    async def get(self, import_id: uuid.UUID, user_id: uuid.UUID) -> StagedImport:
        """Raises StagedImportNotFoundError if missing, expired, or
        belonging to a different user."""
        ...

    @abstractmethod
    async def delete(self, import_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """No-op (not an error) if already gone -- commit and discard
        both want "make sure it's gone", not "assert it was there"."""
        ...
