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
                {
                    **dataclasses.asdict(row),
                    "status": row.status.value,
                    # FINTRACK-17: matched_rule_id is a uuid.UUID | None on
                    # the domain model -- dataclasses.asdict() leaves it as
                    # a raw UUID object, which json.dumps() can't encode.
                    # Bug found by QA Lead's integration tests: the
                    # fixture-based unit tests never touch this real
                    # serialization path, so a real auto-categorised import
                    # (an actual rule match) always raised a 500 here.
                    "matched_rule_id": (
                        str(row.matched_rule_id) if row.matched_rule_id is not None else None
                    ),
                }
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
                # FINTRACK-17: same bug as save() above -- this key was
                # previously dropped entirely on read, silently reverting
                # every row's matched_rule_id to the dataclass default of
                # None even after the write side is fixed. .get() (not
                # r["matched_rule_id"]) also keeps this backward-compatible
                # with any import already staged in Redis under the old
                # payload shape before this fix.
                matched_rule_id=(
                    uuid.UUID(r["matched_rule_id"])
                    if r.get("matched_rule_id") is not None
                    else None
                ),
            )
            for r in data["rows"]
        ]
        return StagedImport(
            id=uuid.UUID(data["id"]),
            user_id=uuid.UUID(data["user_id"]),
            rows=rows,
            created_at=datetime.fromisoformat(data["created_at"]),
        )
