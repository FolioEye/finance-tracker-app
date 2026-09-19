"""RefreshSessionCommand + handler -- the use case for FINTRACK-60
(session persistence via silent token refresh).

See docs/adr/ADR-017-session-persistence-silent-refresh.md for the full
decision. In short: this rotates the refresh token on every use. The
presented token's `jti` is added to the same Redis denylist that
FINTRACK-14's logout writes to (ADR-009), and -- new here -- that
denylist is now actually *read* before a token is honoured. Until this
story, `TokenRevocationStore.is_revoked()` had no callers at all: logout
wrote entries nothing ever checked.

Ordering is deliberate and fail-closed: the old token is revoked BEFORE
the new pair is issued. A crash between the two steps leaves the user
with no valid refresh token (they re-authenticate) rather than two live
ones.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from apps.api.infrastructure.security.token_revocation import TokenRevocationStore
from apps.api.infrastructure.security.token_service import (
    ExpiredTokenError,
    InvalidTokenError,
    TokenPair,
    TokenService,
)


class InvalidRefreshTokenError(Exception):
    """Raised when the presented refresh token cannot be honoured.

    Deliberately ONE exception type for every rejection reason -- missing
    cookie, malformed token, expired token, an access token presented in
    the refresh token's place, or a replayed token that has already been
    rotated away. The route layer turns all of these into an identical
    401, for the same no-enumeration rationale LoginUserHandler documents:
    the caller learns that the session is not valid, never which of those
    five things went wrong.
    """


class RefreshTokenReplayError(InvalidRefreshTokenError):
    """A token that was already rotated away has been presented again.

    A subclass rather than a separate branch so the route's `except
    InvalidRefreshTokenError` still catches it and returns the same 401 --
    but it is distinguishable at the logging layer, because a replay is a
    security signal worth alerting on (FINTRACK-64) while an ordinary
    expiry is routine.
    """


@dataclass(frozen=True)
class RefreshSessionCommand:
    refresh_token: str


@dataclass(frozen=True)
class RefreshSessionResult:
    user_id: uuid.UUID
    tokens: TokenPair


class RefreshSessionHandler:
    def __init__(
        self,
        token_service: TokenService,
        revocation_store: TokenRevocationStore,
    ) -> None:
        self._tokens = token_service
        self._revocation = revocation_store

    async def handle(self, command: RefreshSessionCommand) -> RefreshSessionResult:
        if not command.refresh_token:
            raise InvalidRefreshTokenError("No refresh token presented")

        try:
            claims = self._tokens.decode(command.refresh_token)
        except (ExpiredTokenError, InvalidTokenError) as exc:
            raise InvalidRefreshTokenError("Refresh token is not valid") from exc

        # An access token is signed with the same key and would otherwise
        # decode cleanly here. Checking `type` is what stops a leaked
        # access token being upgraded into a fresh 7-day session.
        if claims.get("type") != "refresh":
            raise InvalidRefreshTokenError("Presented token is not a refresh token")

        jti = claims.get("jti")
        exp = claims.get("exp")
        subject = claims.get("sub")
        if not jti or not exp or not subject:
            # A token missing any of these was not minted by TokenService's
            # issue_pair(); treat it as invalid rather than working around
            # the gap with defaults.
            raise InvalidRefreshTokenError("Refresh token is missing required claims")

        if await self._revocation.is_revoked(jti):
            raise RefreshTokenReplayError("Refresh token has already been used")

        try:
            user_id = uuid.UUID(str(subject))
        except ValueError as exc:
            raise InvalidRefreshTokenError("Refresh token subject is not a valid user id") from exc

        # Burn the presented token first -- see the module docstring for
        # why this ordering, not the reverse.
        await self._revocation.revoke(jti=jti, expires_at_epoch=int(exp))

        tokens = self._tokens.issue_pair(user_id)
        return RefreshSessionResult(user_id=user_id, tokens=tokens)
