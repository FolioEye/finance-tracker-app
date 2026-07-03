"""JWT access + refresh token issuance. python-jose per the fixed FinTrack stack.

See docs/adr/ADR-004-authentication-strategy.md for why this is hand-rolled
rather than a managed auth provider.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from jose import jwt


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    access_token_expires_in_seconds: int


class TokenService:
    def __init__(
        self,
        secret_key: str,
        algorithm: str = "HS256",
        access_token_expire_minutes: int = 15,
        refresh_token_expire_days: int = 7,
    ) -> None:
        if not secret_key:
            raise ValueError("jwt_secret_key must be set via environment, never hardcoded")
        self._secret_key = secret_key
        self._algorithm = algorithm
        self._access_expire = timedelta(minutes=access_token_expire_minutes)
        self._refresh_expire = timedelta(days=refresh_token_expire_days)

    def issue_pair(self, user_id: uuid.UUID) -> TokenPair:
        now = datetime.now(timezone.utc)
        access_payload = {
            "sub": str(user_id),
            "type": "access",
            "iat": now,
            "exp": now + self._access_expire,
        }
        refresh_payload = {
            "sub": str(user_id),
            "type": "refresh",
            "jti": str(uuid.uuid4()),  # unique id -- enables a future revocation list
            "iat": now,
            "exp": now + self._refresh_expire,
        }
        access_token = jwt.encode(access_payload, self._secret_key, algorithm=self._algorithm)
        refresh_token = jwt.encode(refresh_payload, self._secret_key, algorithm=self._algorithm)
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            access_token_expires_in_seconds=int(self._access_expire.total_seconds()),
        )
