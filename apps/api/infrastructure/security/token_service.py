"""JWT access + refresh token issuance. PyJWT per ADR-006.

See docs/adr/ADR-004-authentication-strategy.md for why this is hand-rolled
rather than a managed auth provider, and docs/adr/ADR-006-jwt-library-migration.md
for why PyJWT replaced python-jose.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt


class ExpiredTokenError(Exception):
    """Raised when a token's signature is valid but it has expired."""


class InvalidTokenError(Exception):
    """Raised when a token's signature is invalid or it is otherwise malformed."""


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
            "jti": str(uuid.uuid4()),  # unique id -- kept for parity with the refresh
            # token and future use (e.g. a P2 "log out everywhere" feature);
            # FINTRACK-14's logout does not check this jti against the
            # revocation store -- see ADR-009 for why access-token
            # revocation is out of scope for this story.
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

    def decode(self, token: str) -> dict:
        """Verifies signature + expiry and returns the claims. Used by
        logout (FINTRACK-14) to extract the refresh token's `jti`/`exp`
        without needing a separate parsing path.
        """
        try:
            return jwt.decode(token, self._secret_key, algorithms=[self._algorithm])
        except jwt.ExpiredSignatureError as exc:
            raise ExpiredTokenError("Token has expired") from exc
        except jwt.InvalidTokenError as exc:
            raise InvalidTokenError("Token is invalid") from exc
