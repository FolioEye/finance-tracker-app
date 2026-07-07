"""LogoutUserCommand + handler -- the use case for FINTRACK-14 (Logout).

See docs/adr/ADR-009-login-session-management.md for why this revokes only
the refresh token (via a Redis denylist keyed on its `jti`) and leaves the
access token to expire naturally.
"""
from __future__ import annotations

from dataclasses import dataclass

from apps.api.infrastructure.security.token_revocation import TokenRevocationStore
from apps.api.infrastructure.security.token_service import (
    ExpiredTokenError,
    InvalidTokenError,
    TokenService,
)


class NoActiveSessionError(Exception):
    """Raised when logout is called with no valid refresh token to
    invalidate (missing cookie, or a token that isn't a refresh token)."""


@dataclass(frozen=True)
class LogoutUserCommand:
    refresh_token: str


class LogoutUserHandler:
    def __init__(self, token_service: TokenService, revocation_store: TokenRevocationStore) -> None:
        self._tokens = token_service
        self._revocation = revocation_store

    async def handle(self, command: LogoutUserCommand) -> None:
        if not command.refresh_token:
            raise NoActiveSessionError("No active session to log out of")

        try:
            claims = self._tokens.decode(command.refresh_token)
        except (ExpiredTokenError, InvalidTokenError):
            # Already expired or malformed -- logout is idempotent, there
            # is nothing left to revoke.
            return

        if claims.get("type") != "refresh":
            raise NoActiveSessionError("No active session to log out of")

        jti = claims.get("jti")
        exp = claims.get("exp")
        if jti and exp:
            await self._revocation.revoke(jti=jti, expires_at_epoch=exp)
