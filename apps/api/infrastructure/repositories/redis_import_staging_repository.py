"""Redis-backed staging store for CSV/statement imports pending user
review. Story: FINTRACK-16.

30-minute TTL, matching this codebase's existing pattern for other
short-lived Redis-held state (see infrastructure/security/token_revocation.py's
revoked-jti store and rate_limiter.py) -- a staged import a user never
reviews should not linger indefinitely; the explicit DELETE
(discard_import) endpoint gives an early-exit path, and commit_import.py
also deletes on successful commit.
"""
from __future__ import annotations

import dataclasses
import json
import uuid
from datetime import datetime

from redis.asyncio import Redis

from apps.api.domain.models.import_batch import RowStatus, StagedImport, StagedImportRow
from apps.api.domain.repositories.import_staging_repository import (
    ImportStagingRepository,
    StagedImportNotFoundError,
)

_KEY_PREFIX = "import"
_TTL_SECONDS = 1800  # 30 minutes


def _key(user_id: uuid.UUID, import_id: uuid.UUID) -> str:
    return f"{_KEY_PREFIX}:{user_id}:{import_id}"


class RedisImportStagingRepository(ImportStagingRepository):
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def save(self, staged_import: StagedImport) -> None:
        payload = {
            "id": str(staged_import.id),
            "user_id": str(staged_import.user_id),
            "created_at": staged_import.created_at.isoformat(),
            "rows": [
                {**dataclasses.asdict(row), "status": row.status.value}
                for row in staged_import.rows
            ],
        }
        await self._redis.set(
            _key(staged_import.user_id, staged_import.id),
            json.dumps(payload),
            ex=_TTL_SECONDS,
        )

    async def get(self, import_id: uuid.UUID, user_id: uuid.UUID) -> StagedImport:
        raw = await self._redis.get(_key(user_id, import_id))
        if raw is None:
            raise StagedImportNotFoundError(str(import_id))
        return self._deserialize(raw)

    async def delete(self, import_id: uuid.UUID, user_id: uuid.UUID) -> None:
        await self._redis.delete(_key(user_id, import_id))

    @staticmethod
    def _deserialize(raw: str) -> StagedImport:
        data = json.loads(raw)
        rows = [
            StagedImportRow(
                row_index=r["row_index"],
                raw_date=r["raw_date"],
                raw_amount=r["raw_amount"],
                category=r["category"],
                note=r["note"],
                status=RowStatus(r["status"]),
                warning=r["warning"],
            )
            for r in data["rows"]
        ]
        return StagedImport(
            id=uuid.UUID(data["id"]),
            user_id=uuid.UUID(data["user_id"]),
            rows=rows,
            created_at=datetime.fromisoformat(data["created_at"]),
        )
