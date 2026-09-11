"""Unit tests for RefreshSessionHandler (FINTRACK-60). External deps faked
at the port boundary per constraint matrix -- no real Redis here (see
tests/integration/test_refresh_api.py for the real-API-level equivalents,
and conftest.py for the fakeredis wiring used there).

The real TokenService is used rather than a fake, for the same reason
test_login_logout_user.py gives: this handler branches on real JWT claim
semantics (type, jti, exp, sub), and a hand-rolled fake would either have
to reimplement them or risk diverging from production behaviour.
"""
from __future__ import annotations

import uuid

import pytest

from apps.api.application.commands.refresh_session import (
    InvalidRefreshTokenError,
    RefreshSessionCommand,
    RefreshSessionHandler,
    RefreshTokenReplayError,
)
from apps.api.infrastructure.security.token_service import TokenService

_TEST_SECRET = "test-secret-key-not-for-production-use-only"


class FakeTokenRevocationStore:
    """Same shape as tests/unit/test_login_logout_user.py's fake -- kept
    local rather than imported so this module stands alone if that file
    is ever restructured."""

    def __init__(self) -> None:
        self.revoked: dict[str, int] = {}

    async def revoke(self, jti: str, expires_at_epoch: int) -> None:
        self.revoked[jti] = expires_at_epoch

    async def is_revoked(self, jti: str) -> bool:
        return jti in self.revoked


class ExplodingRevocationStore(FakeTokenRevocationStore):
    """Raises on revoke() to prove the fail-closed ordering: the old token
    is burned BEFORE the new pair is issued, so a mid-operation failure
    must not leave a caller holding a usable new session."""

    async def revoke(self, jti: str, expires_at_epoch: int) -> None:
        raise RuntimeError("redis unavailable")


@pytest.fixture
def tokens() -> TokenService:
    return TokenService(secret_key=_TEST_SECRET)


@pytest.fixture
def store() -> FakeTokenRevocationStore:
    return FakeTokenRevocationStore()


@pytest.fixture
def handler(tokens: TokenService, store: FakeTokenRevocationStore) -> RefreshSessionHandler:
    return RefreshSessionHandler(token_service=tokens, revocation_store=store)


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# Happy path -- AC1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_refresh_token_issues_a_new_pair(handler, tokens, user_id) -> None:
    original = tokens.issue_pair(user_id)

    result = await handler.handle(RefreshSessionCommand(refresh_token=original.refresh_token))

    assert result.user_id == user_id
    assert result.tokens.access_token != original.access_token
    assert result.tokens.refresh_token != original.refresh_token
    assert result.tokens.access_token_expires_in_seconds == 15 * 60


@pytest.mark.asyncio
async def test_rotation_mints_a_fresh_jti_on_both_tokens(handler, tokens, user_id) -> None:
    original = tokens.issue_pair(user_id)
    old_refresh_jti = tokens.decode(original.refresh_token)["jti"]

    result = await handler.handle(RefreshSessionCommand(refresh_token=original.refresh_token))

    new_refresh_jti = tokens.decode(result.tokens.refresh_token)["jti"]
    assert new_refresh_jti != old_refresh_jti
    assert tokens.decode(result.tokens.refresh_token)["type"] == "refresh"
    assert tokens.decode(result.tokens.access_token)["type"] == "access"


@pytest.mark.asyncio
async def test_presented_token_is_revoked_after_use(handler, tokens, store, user_id) -> None:
    original = tokens.issue_pair(user_id)
    old_jti = tokens.decode(original.refresh_token)["jti"]

    await handler.handle(RefreshSessionCommand(refresh_token=original.refresh_token))

    assert await store.is_revoked(old_jti)


@pytest.mark.asyncio
async def test_denylist_entry_expires_with_the_token_not_later(
    handler, tokens, store, user_id
) -> None:
    """The denylist TTL is the token's own exp -- keeping an entry longer
    than the token could ever be valid for would grow the store without
    bound, which is what keeps Redis usage bounded by construction."""
    original = tokens.issue_pair(user_id)
    claims = tokens.decode(original.refresh_token)

    await handler.handle(RefreshSessionCommand(refresh_token=original.refresh_token))

    assert store.revoked[claims["jti"]] == claims["exp"]


# ---------------------------------------------------------------------------
# Replay -- AC5
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replaying_a_rotated_token_raises_replay_error(handler, tokens, user_id) -> None:
    original = tokens.issue_pair(user_id)
    await handler.handle(RefreshSessionCommand(refresh_token=original.refresh_token))

    with pytest.raises(RefreshTokenReplayError):
        await handler.handle(RefreshSessionCommand(refresh_token=original.refresh_token))


def test_replay_error_is_an_invalid_refresh_token_error() -> None:
    """The route catches InvalidRefreshTokenError broadly and returns one
    identical 401. If RefreshTokenReplayError ever stopped subclassing it,
    a replay would escape as an unhandled 500 -- so the relationship is
    asserted, not assumed."""
    assert issubclass(RefreshTokenReplayError, InvalidRefreshTokenError)


@pytest.mark.asyncio
async def test_a_token_revoked_by_logout_is_also_rejected(handler, tokens, store, user_id) -> None:
    """Logout has written to this denylist since FINTRACK-14 with nothing
    reading it. This is the test that the write now has a reader."""
    original = tokens.issue_pair(user_id)
    claims = tokens.decode(original.refresh_token)
    await store.revoke(jti=claims["jti"], expires_at_epoch=claims["exp"])

    with pytest.raises(RefreshTokenReplayError):
        await handler.handle(RefreshSessionCommand(refresh_token=original.refresh_token))


# ---------------------------------------------------------------------------
# Rejections -- AC4, and the token-type guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_token_is_rejected(handler) -> None:
    with pytest.raises(InvalidRefreshTokenError):
        await handler.handle(RefreshSessionCommand(refresh_token=""))


@pytest.mark.asyncio
async def test_malformed_token_is_rejected(handler) -> None:
    with pytest.raises(InvalidRefreshTokenError):
        await handler.handle(RefreshSessionCommand(refresh_token="not-a-jwt"))


@pytest.mark.asyncio
async def test_expired_token_is_rejected(handler, user_id) -> None:
    expired = TokenService(secret_key=_TEST_SECRET, refresh_token_expire_days=-1)
    with pytest.raises(InvalidRefreshTokenError):
        await handler.handle(
            RefreshSessionCommand(refresh_token=expired.issue_pair(user_id).refresh_token)
        )


@pytest.mark.asyncio
async def test_an_access_token_cannot_be_used_to_refresh(handler, tokens, user_id) -> None:
    """Both tokens are signed with the same key, so an access token decodes
    cleanly here. The `type` claim is the only thing stopping a leaked
    15-minute access token from being upgraded into a fresh 7-day session."""
    pair = tokens.issue_pair(user_id)
    with pytest.raises(InvalidRefreshTokenError):
        await handler.handle(RefreshSessionCommand(refresh_token=pair.access_token))


@pytest.mark.asyncio
async def test_token_signed_with_a_different_secret_is_rejected(handler, user_id) -> None:
    foreign = TokenService(secret_key="a-completely-different-signing-secret-value")
    with pytest.raises(InvalidRefreshTokenError):
        await handler.handle(
            RefreshSessionCommand(refresh_token=foreign.issue_pair(user_id).refresh_token)
        )


# ---------------------------------------------------------------------------
# Fail-closed ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_new_tokens_are_issued_if_revocation_fails(tokens, user_id) -> None:
    """Revoke-before-issue means a store failure denies the refresh rather
    than handing out a second live session. If the ordering were ever
    reversed, this test would fail by returning a result instead of
    raising -- which is the whole point of asserting it."""
    handler = RefreshSessionHandler(
        token_service=tokens, revocation_store=ExplodingRevocationStore()
    )
    original = tokens.issue_pair(user_id)

    with pytest.raises(RuntimeError):
        await handler.handle(RefreshSessionCommand(refresh_token=original.refresh_token))
